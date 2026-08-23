"""`import_corpus.py`: a dev-only, offline scaffold generator — never a
corpus input format `cairn index` reads. Human review is mandatory; this
tests the scaffold and preview, not that the output is publishable as-is."""

from __future__ import annotations

import contextlib
import io
import json
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


class TestBatchMode(unittest.TestCase):
    def run_main(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = import_corpus.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def _sources(self, src_dir: Path) -> None:
        (src_dir / "notice1.txt").write_text(
            "First Notice\n\nBody text about a program.\n", encoding="utf-8"
        )
        (src_dir / "notice2.html").write_text(
            "<html><head><title>Second Notice</title></head>"
            "<body><p>Different body text entirely.</p></body></html>",
            encoding="utf-8",
        )
        # Not a source: same skip rule cairn.corpus applies to READMEs, and a
        # batch run should not choke on an unrelated file sitting alongside
        # the real inputs.
        (src_dir / "notes.md").write_text("not an input format\n", encoding="utf-8")

    def test_batch_scaffolds_every_txt_and_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            self._sources(src_dir)
            code, out, err = self.run_main("--batch", str(src_dir), "-o", str(out_dir))
            self.assertEqual(code, 0, err)
            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()), ["notice1.md", "notice2.md"]
            )
            self.assertIn("2/2 file(s) scaffolded", out)
            doc1 = load_document(out_dir / "notice1.md")
            doc2 = load_document(out_dir / "notice2.md")
            self.assertEqual(doc1.doc_id, "review-notice1")
            self.assertEqual(doc2.title, "Second Notice")

    def test_batch_reports_partial_failure_without_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            self._sources(src_dir)
            (src_dir / "empty.txt").write_text("   \n\n  \n", encoding="utf-8")
            code, out, err = self.run_main("--batch", str(src_dir), "-o", str(out_dir))
            self.assertEqual(code, 1)
            self.assertIn("2/3 file(s) scaffolded", out)
            self.assertIn("1 file(s) failed", err)
            # The two good files still made it out despite the third failing.
            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()), ["notice1.md", "notice2.md"]
            )

    def test_batch_rejects_id_and_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            self._sources(src_dir)
            code, _, err = self.run_main(
                "--batch", str(src_dir), "-o", str(out_dir), "--id", "x"
            )
            self.assertEqual(code, 1)
            self.assertIn("not valid with --batch", err)

    def test_batch_on_a_missing_directory_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main(
                "--batch", str(Path(tmp) / "nowhere"), "-o", str(Path(tmp) / "out")
            )
            self.assertEqual(code, 1)
            self.assertIn("not a directory", err)

    def test_batch_on_an_empty_directory_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "in"
            src_dir.mkdir()
            (src_dir / "notes.md").write_text("wrong format\n", encoding="utf-8")
            code, _, err = self.run_main(
                "--batch", str(src_dir), "-o", str(Path(tmp) / "out")
            )
            self.assertEqual(code, 1)
            self.assertIn("no .txt or .html files", err)


if __name__ == "__main__":
    unittest.main()


class TestDuplicatedTitle(unittest.TestCase):
    """`docs/pilot-usagov.md`, Finding 1, made mechanical: a first paragraph
    that restates the title is dropped, because it was measured to out-score
    the real answering passage. Only the first paragraph, only an exact
    normalised match — anything looser is a judgement the reviewer keeps."""

    def test_exact_restatement_is_dropped(self):
        kept, dropped = import_corpus.drop_duplicated_title(
            ["How to apply for SNAP", "Every state issues benefits on an EBT card."],
            "How to apply for SNAP",
        )
        self.assertTrue(dropped)
        self.assertEqual(kept, ["Every state issues benefits on an EBT card."])

    def test_case_whitespace_and_trailing_punctuation_do_not_matter(self):
        kept, dropped = import_corpus.drop_duplicated_title(
            ["  how TO apply   for snap. ", "Body."], "How to apply for SNAP"
        )
        self.assertTrue(dropped)
        self.assertEqual(kept, ["Body."])

    def test_a_sentence_containing_the_title_is_content(self):
        paragraphs = ["How to apply for SNAP depends on your state.", "Body."]
        kept, dropped = import_corpus.drop_duplicated_title(paragraphs, "How to apply for SNAP")
        self.assertFalse(dropped)
        self.assertEqual(kept, paragraphs)

    def test_a_restated_title_is_dropped_wherever_it_sits(self):
        # sonomacounty.gov: breadcrumbs first, the title restated third.
        paragraphs = ["Home › Human Services", "Share this:", "How to apply for SNAP", "Body."]
        kept, dropped = import_corpus.drop_duplicated_title(paragraphs, "How to apply for SNAP")
        self.assertTrue(dropped)
        self.assertEqual(kept, ["Home › Human Services", "Share this:", "Body."])

    def test_html_h1_matching_the_title_never_reaches_the_scaffold(self):
        html = (
            "<html><head><title>Food Stamps</title></head><body>"
            "<h1>Food Stamps</h1><p>Apply at your county office.</p></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.html"
            src.write_text(html, encoding="utf-8")
            out_path = Path(tmp) / "page.md"
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = import_corpus.main([str(src), "-o", str(out_path)])
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn("Dropped the first paragraph", out.getvalue())
            doc = load_document(out_path)
            self.assertEqual(len(doc.passages), 1)
            self.assertEqual(doc.passages[0].text, "Apply at your county office.")

    def test_a_page_that_is_only_its_title_is_an_error_not_an_empty_document(self):
        html = (
            "<html><head><title>Food Stamps</title></head>"
            "<body><h1>Food Stamps</h1></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.html"
            src.write_text(html, encoding="utf-8")
            out_path = Path(tmp) / "page.md"
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = import_corpus.main([str(src), "-o", str(out_path)])
            self.assertEqual(code, 1)
            self.assertIn("nothing but its own title", err.getvalue())
            self.assertFalse(out_path.exists())


class TestProvenance(unittest.TestCase):
    """`source:` and `fetched_at:` are written from the fetch manifest or
    `--source`, never retyped; `reviewed_at:` is never written by the
    scaffold, because it asserts a person read the document."""

    def run_main(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = import_corpus.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_source_flag_lands_in_front_matter(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "n.txt"
            src.write_text("Body paragraph.\n", encoding="utf-8")
            out_path = Path(tmp) / "n.md"
            code, _, err = self.run_main(
                str(src), "-o", str(out_path), "--source", "https://example.gov/n"
            )
            self.assertEqual(code, 0, err)
            text = out_path.read_text(encoding="utf-8")
            self.assertIn("source: https://example.gov/n\n", text)
            self.assertNotIn("reviewed_at", text)
            self.assertNotIn("fetched_at", text)
            load_document(out_path)  # inert keys: still a valid document

    def test_batch_reads_the_manifest_for_url_date_and_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            (src_dir / "a.txt").write_text("Alpha body.\n", encoding="utf-8")
            (src_dir / "b.txt").write_text("Cuerpo beta.\n", encoding="utf-8")
            (src_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "file": "a.txt",
                                "url": "https://example.gov/a",
                                "fetched_at": "2026-08-23",
                            },
                            {
                                "file": "b.txt",
                                "url": "https://example.gov/es/b",
                                "fetched_at": "2026-08-23",
                                "lang": "es",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            code, out, err = self.run_main("--batch", str(src_dir), "-o", str(out_dir))
            self.assertEqual(code, 0, err)
            self.assertIn("Provenance from", out)
            a = (out_dir / "a.md").read_text(encoding="utf-8")
            b = (out_dir / "b.md").read_text(encoding="utf-8")
            self.assertIn("source: https://example.gov/a\n", a)
            self.assertIn("fetched_at: 2026-08-23\n", a)
            self.assertIn("lang: en\n", a)
            self.assertIn("lang: es\n", b)  # the manifest's language wins over --lang
            self.assertEqual(load_document(out_dir / "b.md").lang, "es")

    def test_batch_without_a_manifest_is_simply_unprovenanced(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            (src_dir / "a.txt").write_text("Alpha body.\n", encoding="utf-8")
            code, out, _ = self.run_main("--batch", str(src_dir), "-o", str(out_dir))
            self.assertEqual(code, 0)
            self.assertNotIn("Provenance from", out)
            self.assertNotIn("source:", (out_dir / "a.md").read_text(encoding="utf-8"))

    def test_a_corrupt_manifest_stops_the_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            (src_dir / "a.txt").write_text("Alpha body.\n", encoding="utf-8")
            (src_dir / "manifest.json").write_text("{not json", encoding="utf-8")
            code, _, err = self.run_main("--batch", str(src_dir), "-o", str(out_dir))
            self.assertEqual(code, 1)
            self.assertIn("unreadable manifest.json", err)
            self.assertFalse(out_dir.exists())

    def test_source_is_rejected_with_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "in"
            src_dir.mkdir()
            (src_dir / "a.txt").write_text("Alpha body.\n", encoding="utf-8")
            code, _, err = self.run_main(
                "--batch", str(src_dir), "-o", str(Path(tmp) / "out"), "--source", "x"
            )
            self.assertEqual(code, 1)
            self.assertIn("not valid with --batch", err)


class TestExtractorShape(unittest.TestCase):
    """The extractor produces the shape `docs/pilot-usagov.md` transcribed by
    hand: main content only, `##` headings in their own block, a list or a
    table as one block. Each case is something the 2026-08-23 smoke run over
    28 federal pages got wrong before the rule existed."""

    def test_main_content_scoping_drops_everything_outside_main(self):
        html = (
            "<html><head><title>T</title></head><body>"
            "<div>Skip to main content</div><nav>Menu</nav>"
            "<main><p>The real paragraph about the program.</p></main>"
            "<footer>7500 Security Boulevard</footer><div>After main</div>"
            "</body></html>"
        )
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["The real paragraph about the program."])

    def test_role_main_counts_as_main_and_nested_divs_do_not_close_it(self):
        html = (
            '<div>chrome</div><div role="main"><div><p>content</p></div>'
            "<p>more content</p></div><div>chrome</div>"
        )
        self.assertEqual(import_corpus.extract_html(html)[0], ["content", "more content"])
        html = '<div>chrome</div><div role="main"><p>content</p></div><div>chrome</div>'
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["content"])

    def test_a_page_without_main_is_read_whole(self):
        html = "<body><p>One.</p><p>Two.</p></body>"
        self.assertEqual(import_corpus.extract_html(html)[0], ["One.", "Two."])

    def test_landmarks_and_form_controls_are_dropped_but_a_forms_prose_is_kept(self):
        # cdss.ca.gov wraps the whole page in one <form> (ASP.NET), so a form
        # is not chrome; its controls are.
        html = (
            "<main><header>site header</header><p>Body text here.</p>"
            "<aside>related links</aside>"
            "<form><p>Apply online in three steps.</p><label>Email</label>"
            "<input value='x'><select><option>One</option></select>"
            "<button>Submit now</button></form>"
            "<footer>page footer</footer></main>"
        )
        self.assertEqual(
            import_corpus.extract_html(html)[0],
            ["Body text here.", "Apply online in three steps."],
        )

    def test_an_unclosed_nav_is_closed_by_main(self):
        html = "<nav>Menu<main><p>Visible content here.</p></main>"
        self.assertEqual(import_corpus.extract_html(html)[0], ["Visible content here."])

    def test_aria_hidden_region_is_closed_by_its_own_end_tag(self):
        # A hidden <div> wrapping a search form swallowed every medicare.gov
        # page when the skip was a counter rather than a stack.
        html = (
            '<div aria-hidden="true"><form><input></form></div>'
            "<main><p>Visible content.</p></main>"
        )
        self.assertEqual(import_corpus.extract_html(html)[0], ["Visible content."])

    def test_headings_become_hash_lines_and_h1_becomes_the_title(self):
        html = (
            "<head><title>Page | Site | Department</title></head>"
            "<main><h1>Medicare Savings Programs</h1><h2>How to qualify</h2>"
            "<p>Income limits apply.</p><h3>QMB</h3><p>Helps pay premiums.</p></main>"
        )
        paragraphs, title = import_corpus.extract_html(html)
        self.assertEqual(title, "Medicare Savings Programs")
        self.assertEqual(
            paragraphs,
            [
                "Medicare Savings Programs",
                "## How to qualify",
                "Income limits apply.",
                "### QMB",
                "Helps pay premiums.",
            ],
        )
        # And through the scaffold, the chunker attaches each heading to the
        # passage under it and the H1 is removed as the restated title.
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "p.html"
            src.write_text(html, encoding="utf-8")
            out_path = Path(tmp) / "p.md"
            with contextlib.redirect_stdout(io.StringIO()):
                import_corpus.main([str(src), "-o", str(out_path)])
            doc = load_document(out_path)
            self.assertEqual(doc.title, "Medicare Savings Programs")
            self.assertEqual(
                [p.text for p in doc.passages],
                ["## How to qualify\nIncome limits apply.", "### QMB\nHelps pay premiums."],
            )

    def test_title_tag_is_the_fallback_when_there_is_no_h1(self):
        html = "<head><title>Only Title</title></head><main><p>Body.</p></main>"
        self.assertEqual(import_corpus.extract_html(html)[1], "Only Title")

    def test_a_list_is_one_block(self):
        html = (
            "<main><p>To check your balance:</p><ul><li>Check your receipt.</li>"
            "<li>Use the mobile app</li><li>Call the office.</li></ul></main>"
        )
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(
            paragraphs,
            [
                "To check your balance:",
                "Check your receipt. Use the mobile app; Call the office.",
            ],
        )

    def test_nested_lists_flatten_into_the_parent_block(self):
        html = (
            "<main><ul><li>Outer<ul><li>Inner one</li><li>Inner two</li></ul></li></ul></main>"
        )
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(paragraphs, ["Outer; Inner one; Inner two"])

    def test_a_table_is_one_block_with_one_line_per_row(self):
        html = (
            "<main><table><tr><th>Your situation</th><th>Limit</th></tr>"
            "<tr><td>Individual</td><td>$1,350</td></tr>"
            "<tr><td>Married couple</td><td>$1,824</td></tr></table></main>"
        )
        paragraphs, _ = import_corpus.extract_html(html)
        self.assertEqual(
            paragraphs,
            ["Your situation | Limit\nIndividual | $1,350\nMarried couple | $1,824"],
        )


class TestTidyBlocks(unittest.TestCase):
    def test_colon_introducer_joins_the_block_it_introduces(self):
        intro, body, after = (
            "If you qualify for the QMB program:",
            "Providers cannot bill you.",
            "Show both cards.",
        )
        kept, dropped = import_corpus.tidy_blocks([intro, body, after])
        self.assertEqual(kept, [f"{intro} {body}", after])
        self.assertEqual(dropped, 0)

    def test_a_heading_is_never_joined_in_either_direction(self):
        blocks = ["Limits for 2026:", "## QMB", "Helps pay premiums."]
        kept, _ = import_corpus.tidy_blocks(blocks)
        self.assertEqual(kept, blocks)

    def test_a_table_block_is_not_extended_by_a_following_colon_rule(self):
        note = "Limits are higher in Alaska."
        kept, _ = import_corpus.tidy_blocks(["Limits:", "A | 1\nB | 2", note])
        self.assertEqual(kept, ["Limits: A | 1\nB | 2", note])

    def test_a_short_question_block_becomes_a_heading(self):
        kept, _ = import_corpus.tidy_blocks(
            ["## Who Is Eligible?", "Who Is Eligible?", "You may be eligible if you live here."]
        )
        expected = ["## Who Is Eligible?"] * 2 + ["You may be eligible if you live here."]
        self.assertEqual(kept, expected)
        long_question = "Is there anything else I should know before I apply for this program?"
        kept, _ = import_corpus.tidy_blocks([long_question])
        self.assertEqual(kept, [long_question])

    def test_short_fragments_without_digits_are_dropped_and_counted(self):
        kept, dropped = import_corpus.tidy_blocks(
            [
                "Begin",
                "Next step",
                "Human Services Department",
                "Individual $1,350",
                "Limits apply.",
                "Contact your state office",
                "## Tools",
            ]
        )
        self.assertEqual(
            kept,
            ["Individual $1,350", "Limits apply.", "Contact your state office", "## Tools"],
        )
        self.assertEqual(dropped, 3)
