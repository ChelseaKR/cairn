"""`cairn diff`: what changed between two corpus directories. Read-only,
advisory only."""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.corpus_diff import diff_corpora, render

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"


def write_doc(directory: Path, name: str, *, doc_id: str, title: str, body: str) -> Path:
    path = directory / name
    path.write_text(
        f"---\nid: {doc_id}\ntitle: {title}\nlang: en\n---\n{body}", encoding="utf-8"
    )
    return path


class TestDiffCorpora(unittest.TestCase):
    def test_a_corpus_against_itself_has_no_diff(self):
        self.assertEqual(diff_corpora(DEMO, DEMO), ())
        self.assertEqual(render(diff_corpora(DEMO, DEMO)), "No document changes.")

    def test_an_empty_directory_is_a_legitimate_empty_side_not_an_error(self):
        # A corpus not yet written, or whose last document was just deleted,
        # is a real side of a diff — `load_corpus` alone would refuse this.
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            self.assertEqual(diff_corpora(old, new), ())
            write_doc(new, "a.md", doc_id="a", title="A", body="Text.\n")
            diffs = diff_corpora(old, new)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "added")

    def test_a_missing_directory_is_still_an_error(self):
        from cairn.corpus import CorpusError

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError):
                diff_corpora(Path(tmp) / "nowhere", Path(tmp))

    def test_an_added_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(new, "a.md", doc_id="a", title="A", body="A new program.\n")
            diffs = diff_corpora(old, new)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "added")
            self.assertEqual(diffs[0].doc_id, "a")

    def test_a_removed_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "a.md", doc_id="a", title="A", body="A program.\n")
            diffs = diff_corpora(old, new)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "removed")

    def test_an_unchanged_document_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "a.md", doc_id="a", title="A", body="Same text.\n")
            write_doc(new, "a.md", doc_id="a", title="A", body="Same text.\n")
            self.assertEqual(diff_corpora(old, new), ())

    def test_a_changed_single_passage_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "a.md", doc_id="a", title="A", body="Old text.\n")
            write_doc(new, "a.md", doc_id="a", title="A", body="New text.\n")
            diffs = diff_corpora(old, new)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "changed")
            self.assertEqual(len(diffs[0].passage_shifts), 1)
            shift = diffs[0].passage_shifts[0]
            self.assertEqual(shift.ordinal, 1)
            self.assertEqual(shift.old_text, "Old text.")
            self.assertEqual(shift.new_text, "New text.")

    def test_an_inserted_paragraph_shifts_every_ordinal_after_it(self):
        # The exact case the module exists to make visible: a paragraph
        # inserted in the middle renumbers everything after it, so every
        # later passage id now points at different text — not just the one
        # that was literally inserted.
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "a.md", doc_id="a", title="A", body="First.\n\nSecond.\n\nThird.\n")
            write_doc(
                new, "a.md", doc_id="a", title="A",
                body="First.\n\nInserted.\n\nSecond.\n\nThird.\n",
            )
            diffs = diff_corpora(old, new)
            self.assertEqual(len(diffs), 1)
            shifts = diffs[0].passage_shifts
            # #1 (First.) is unaffected; #2, #3, #4 all now differ from what
            # #2 and #3 used to hold.
            self.assertEqual([s.ordinal for s in shifts], [2, 3, 4])
            self.assertIsNone(shifts[2].old_text, "ordinal 4 is new, not a mutation")

    def test_a_shortened_document_reports_a_removed_ordinal(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "a.md", doc_id="a", title="A", body="First.\n\nSecond.\n")
            write_doc(new, "a.md", doc_id="a", title="A", body="First.\n")
            diffs = diff_corpora(old, new)
            shift = diffs[0].passage_shifts[0]
            self.assertEqual(shift.ordinal, 2)
            self.assertIsNone(shift.new_text)

    def test_render_lists_added_removed_and_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            write_doc(old, "gone.md", doc_id="gone", title="Gone", body="Bye.\n")
            write_doc(old, "same.md", doc_id="same", title="Same", body="Text.\n")
            write_doc(new, "same.md", doc_id="same", title="Same", body="Text.\n")
            write_doc(new, "fresh.md", doc_id="fresh", title="Fresh", body="Hi.\n")
            text = render(diff_corpora(old, new))
            self.assertIn("added   fresh", text)
            self.assertIn("removed gone", text)
            self.assertNotIn("same", text)
            self.assertIn("Advisory only", text)


class TestDiffCli(unittest.TestCase):
    def run_cli(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cairn_diff_needs_no_config_or_index(self):
        code, out, err = self.run_cli("diff", str(DEMO), str(DEMO))
        self.assertEqual(code, 0, err)
        self.assertIn("No document changes.", out)

    def test_cairn_diff_reports_a_real_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy"
            shutil.copytree(DEMO, copy)
            edited = next(copy.glob("*.md"))
            edited.write_text(
                edited.read_text(encoding="utf-8") + "\nAn appended paragraph.\n",
                encoding="utf-8",
            )
            code, out, err = self.run_cli("diff", str(DEMO), str(copy))
            self.assertEqual(code, 0, err)
            self.assertIn("changed", out)
            self.assertNotIn("No document changes.", out)


if __name__ == "__main__":
    unittest.main()
