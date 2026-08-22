"""`import_corpus.py`: a dev-only, offline scaffold generator — never a
corpus input format `cairn index` reads. Human review is mandatory; this
tests the scaffold and preview, not that the output is publishable as-is."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import import_corpus
from cairn.corpus import load_document


class TestSlugify(unittest.TestCase):
    def test_ordinary_title(self):
        self.assertEqual(
            import_corpus.slugify("Winter Heating Assistance"), "winter-heating-assistance"
        )

    def test_starts_with_a_digit_gets_prefixed(self):
        slug = import_corpus.slugify("2024 Winter Credit")
        self.assertTrue(slug[0].isalpha())
        self.assertRegex(slug, r"^[a-z][a-z0-9._:-]*$")

    def test_empty_title_still_produces_a_valid_slug(self):
        slug = import_corpus.slugify("!!!")
        self.assertTrue(slug)
        self.assertTrue(slug[0].isalpha())


class TestExtractText(unittest.TestCase):
    def test_splits_on_blank_lines(self):
        paragraphs = import_corpus.extract_text("First.\n\nSecond.\n\nThird.\n")
        self.assertEqual(paragraphs, ["First.", "Second.", "Third."])

    def test_collapses_internal_whitespace(self):
        paragraphs = import_corpus.extract_text("Line one\nline two   still one para.\n")
        self.assertEqual(paragraphs, ["Line one line two still one para."])


class TestExtractHtml(unittest.TestCase):
    def test_title_tag_is_captured_even_though_head_is_a_skip_tag(self):
        # Regression: <title> lives inside <head>, and <head> suppresses
        # body text — the title must not be swallowed by that same guard.
        html = "<html><head><title>My Title</title></head><body><p>Hi.</p></body></html>"
        paragraphs, title = import_corpus.extract_html(html)
        self.assertEqual(title, "My Title")
        self.assertEqual(paragraphs, ["Hi."])

    def test_script_and_style_content_is_dropped(self):
        html = (
            "<html><body><style>body{color:red}</style>"
            "<p>Real text.</p><script>doStuff();</script></body></html>"
        )
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["Real text."])
        self.assertNotIn("doStuff", " ".join(paragraphs))
        self.assertNotIn("color", " ".join(paragraphs))

    def test_nav_content_is_dropped(self):
        html = "<html><body><nav>Home | About</nav><p>The real content.</p></body></html>"
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["The real content."])

    def test_block_tags_separate_paragraphs(self):
        html = "<div>One</div><div>Two</div><p>Three</p>"
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["One", "Two", "Three"])

    def test_no_title_tag_gives_none(self):
        _, title = import_corpus.extract_html("<body><p>No title here.</p></body>")
        self.assertIsNone(title)


class TestBuildScaffold(unittest.TestCase):
    def test_review_marker_never_reaches_the_body(self):
        # The whole point: the review note must be inert front matter, never
        # body text — body text becomes a real, scored, retrievable passage
        # the moment this file is indexed.
        text = import_corpus.build_scaffold(
            ["Real paragraph one.", "Real paragraph two."],
            doc_id="review-x", title="X", lang="en",
        )
        front_matter, _, body = text.partition("---\n")[2].partition("---\n")
        self.assertIn("review: unreviewed", front_matter)
        self.assertNotIn("review", body.lower())

    def test_the_scaffold_loads_as_a_real_document(self):
        text = import_corpus.build_scaffold(
            ["Paragraph one.", "Paragraph two."], doc_id="review-x", title="X", lang="en"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(text, encoding="utf-8")
            doc = load_document(path)
            self.assertEqual(doc.doc_id, "review-x")
            self.assertEqual(len(doc.passages), 2)
            self.assertFalse(doc.synthetic)


class TestMainCli(unittest.TestCase):
    def run_main(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = import_corpus.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_text_file_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notice.txt"
            src.write_text("Title Line\n\nBody paragraph about a program.\n", encoding="utf-8")
            out_path = Path(tmp) / "out.md"
            code, out, err = self.run_main(str(src), "-o", str(out_path), "--title", "Notice")
            self.assertEqual(code, 0, err)
            self.assertTrue(out_path.is_file())
            self.assertIn("REVIEW REQUIRED", out)
            self.assertIn("Chunk preview", out)
            doc = load_document(out_path)
            self.assertEqual(doc.doc_id, "review-notice")
            self.assertEqual(len(doc.passages), 2)

    def test_html_file_end_to_end_with_explicit_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.html"
            src.write_text(
                "<html><head><title>Bus Pass</title></head>"
                "<body><p>Who can get it? Anyone eligible.</p></body></html>",
                encoding="utf-8",
            )
            out_path = Path(tmp) / "out.md"
            code, out, err = self.run_main(
                str(src), "-o", str(out_path), "--id", "bus-pass-en", "--lang", "en"
            )
            self.assertEqual(code, 0, err)
            doc = load_document(out_path)
            self.assertEqual(doc.doc_id, "bus-pass-en")
            self.assertEqual(doc.title, "Bus Pass")

    def test_a_missing_input_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main(
                str(Path(tmp) / "nope.txt"), "-o", str(Path(tmp) / "out.md")
            )
            self.assertEqual(code, 1)
            self.assertIn("no such file", err)

    def test_empty_extraction_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "empty.txt"
            src.write_text("   \n\n   \n", encoding="utf-8")
            code, _, err = self.run_main(str(src), "-o", str(Path(tmp) / "out.md"))
            self.assertEqual(code, 1)
            self.assertIn("no paragraph text", err)

    def test_never_wired_into_cairn_index(self):
        # Structural guard against scope creep: this script must stay a
        # standalone preprocessing convenience, never an ingestion path.
        import cairn.corpus
        import cairn.index

        self.assertNotIn("import_corpus", vars(cairn.corpus))
        self.assertNotIn("import_corpus", vars(cairn.index))


if __name__ == "__main__":
    unittest.main()
