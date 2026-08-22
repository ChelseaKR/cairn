"""`cairn lint`: read-only corpus checks that report every problem found
rather than stopping at the first one, and never write an index."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.lint import lint_corpus, render

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"


def write_doc(directory: Path, name: str, *, front_matter: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return path


class TestLintCorpus(unittest.TestCase):
    def test_demo_corpus_lints_clean(self):
        report = lint_corpus(DEMO)
        self.assertTrue(report.ok)
        self.assertEqual(report.warning_count, 0)
        self.assertEqual(report.doc_count, 10)

    def test_it_writes_nothing_and_touches_no_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "a.md",
                front_matter="id: a\ntitle: A\nlang: en",
                body="Some body text about a benefit program.\n",
            )
            before = sorted(p.name for p in corpus.iterdir())
            lint_corpus(corpus)
            after = sorted(p.name for p in corpus.iterdir())
            self.assertEqual(before, after, "lint must not create or modify any file")

    def test_a_malformed_document_is_a_finding_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "good.md",
                front_matter="id: good\ntitle: Good\nlang: en",
                body="A perfectly fine passage about a program.\n",
            )
            write_doc(
                corpus, "bad.md",
                front_matter="id: bad\ntitle: Bad",  # missing required `lang`
                body="Body.\n",
            )
            report = lint_corpus(corpus)
            self.assertFalse(report.ok)
            self.assertEqual(report.doc_count, 1, "the good document still loads")
            self.assertEqual(report.error_count, 1)
            self.assertTrue(
                any("bad.md" in i.path and "lang" in i.message for i in report.issues)
            )

    def test_two_malformed_documents_are_both_reported(self):
        # The point of not stopping at the first error: an author fixing a
        # corpus one mistake at a time should see every mistake at once.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(corpus, "bad1.md", front_matter="id: b1\ntitle: T", body="X.\n")
            write_doc(corpus, "bad2.md", front_matter="id: b2\ntitle: T", body="Y.\n")
            report = lint_corpus(corpus)
            self.assertEqual(report.error_count, 2)
            self.assertEqual(report.doc_count, 0)

    def test_duplicate_doc_id_is_reported_as_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "one.md",
                front_matter="id: same\ntitle: One\nlang: en",
                body="First document body about a program.\n",
            )
            write_doc(
                corpus, "two.md",
                front_matter="id: same\ntitle: Two\nlang: en",
                body="Second document body about a program.\n",
            )
            report = lint_corpus(corpus)
            self.assertFalse(report.ok)
            self.assertEqual(report.doc_count, 1, "only the first duplicate loads")
            self.assertTrue(any("duplicate doc id" in i.message for i in report.issues))

    def test_a_passage_with_no_scoring_terms_is_a_warning(self):
        # Title too short to survive `MIN_TERM_LENGTH`, body with no word
        # characters at all: the exact text `cairn index` would score this
        # passage on tokenizes to nothing, so no question can ever retrieve
        # it, but it is a real, loadable passage — a warning, not an error.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "empty.md",
                front_matter="id: empty\ntitle: AB\nlang: en",
                body="!!! ??? ...\n",
            )
            report = lint_corpus(corpus)
            self.assertTrue(report.ok, "an unretrievable passage is a warning, not an error")
            self.assertEqual(report.warning_count, 1)
            issue = report.issues[0]
            self.assertEqual(issue.severity, "warning")
            self.assertIn("empty#1", issue.message)
            self.assertIn("no scoring terms", issue.message)

    def test_a_language_too_small_for_the_df_floor_is_a_warning(self):
        # The exact reproduction DESIGN.md describes by hand: one passage in
        # a language on its own makes every one of its terms clear the
        # document-frequency ratio, so the floor exempts all of them instead
        # of suppressing the whole passage to a 0.0 score.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "lone.md",
                front_matter="id: lone\ntitle: Assistance\nlang: vi",
                body="Financial assistance program details for eligible residents.\n",
            )
            report = lint_corpus(corpus)
            self.assertTrue(report.ok)
            self.assertEqual(report.warning_count, 1)
            issue = report.issues[0]
            self.assertEqual(issue.path, "[vi]")
            self.assertIn("document-frequency floor", issue.message)

    def test_reachability_check_is_skipped_when_a_structural_error_stands(self):
        # Building an index around a corpus already flagged broken would just
        # repeat what `load_corpus` itself refuses; the reachability warning
        # needs a real index, so it only runs over a corpus that parses.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(corpus, "bad.md", front_matter="id: b\ntitle: T", body="X.\n")
            report = lint_corpus(corpus)
            self.assertFalse(report.ok)
            self.assertFalse(
                any(i.path.startswith("[") for i in report.issues),
                "no per-language reachability warning without a buildable index",
            )

    def test_single_term_reachability_is_checked_against_the_given_threshold(self):
        # No real passage's single strongest term reaches a threshold this
        # high, so every passage in a normal corpus is flagged — a
        # deliberately extreme threshold, chosen so the test does not need to
        # hand-engineer term frequencies to land below a realistic one (that
        # is `tests/test_retrieve.py`'s job, precisely).
        report = lint_corpus(DEMO, threshold=0.99)
        self.assertTrue(report.ok, "still only warnings, no structural error")
        self.assertGreater(report.warning_count, 0)
        self.assertTrue(
            all("no single term in" in i.message for i in report.issues),
            report.issues,
        )

    def test_single_term_reachability_is_quiet_at_a_low_threshold(self):
        report = lint_corpus(DEMO, threshold=0.0)
        self.assertEqual(report.warning_count, 0)

    def test_default_threshold_is_the_shipped_config_default(self):
        from cairn.config import Config
        from cairn.lint import DEFAULT_THRESHOLD

        self.assertEqual(DEFAULT_THRESHOLD, Config().threshold)

    def test_an_empty_scoring_passage_is_not_also_flagged_for_reachability(self):
        # It already got the more specific "no scoring terms at all" finding;
        # a second warning saying the same thing a different way is noise.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "empty.md",
                front_matter="id: empty\ntitle: AB\nlang: en",
                body="!!! ??? ...\n",
            )
            report = lint_corpus(corpus, threshold=0.0)  # would flag everything else
            self.assertEqual(report.warning_count, 1)
            self.assertIn("no scoring terms", report.issues[0].message)

    def test_render_reports_clean_and_dirty_corpora(self):
        clean = render(lint_corpus(DEMO))
        self.assertIn("No issues found.", clean)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(corpus, "bad.md", front_matter="id: b\ntitle: T", body="X.\n")
            dirty = render(lint_corpus(corpus))
            self.assertIn("ERROR", dirty)
            self.assertIn("1 error(s), 0 warning(s)", dirty)


class TestStaleness(unittest.TestCase):
    """`--max-age-days` is opt-in: off by default, so a corpus that has
    never adopted `reviewed_at` stays exactly as quiet as before."""

    def test_off_by_default_even_with_no_reviewed_at_anywhere(self):
        report = lint_corpus(DEMO)  # no max_age_days passed
        self.assertTrue(report.ok)
        self.assertEqual(report.warning_count, 0)

    def test_missing_reviewed_at_is_a_warning_once_opted_in(self):
        report = lint_corpus(DEMO, max_age_days=30)
        self.assertTrue(report.ok, "still only warnings")
        self.assertEqual(report.warning_count, 10, "one per demo document")
        self.assertTrue(
            all("no 'reviewed_at'" in i.message for i in report.issues)
        )

    def test_a_recent_reviewed_at_is_quiet(self):
        from datetime import date

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "a.md",
                front_matter="id: a\ntitle: A\nlang: en\nreviewed_at: 2026-01-01",
                body=(
                    "Some content about a benefits program for residents.\n\n"
                    "Additional details about eligibility and application deadlines "
                    "apply here.\n"
                ),
            )
            report = lint_corpus(
                corpus, max_age_days=30, as_of=date(2026, 1, 15)
            )
            self.assertEqual(report.warning_count, 0)

    def test_a_stale_reviewed_at_is_a_warning(self):
        from datetime import date

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "a.md",
                front_matter="id: a\ntitle: A\nlang: en\nreviewed_at: 2026-01-01",
                body=(
                    "Some content about a benefits program for residents.\n\n"
                    "Additional details about eligibility and application deadlines "
                    "apply here.\n"
                ),
            )
            report = lint_corpus(
                corpus, max_age_days=30, as_of=date(2026, 6, 1)
            )
            self.assertEqual(report.warning_count, 1)
            issue = report.issues[0]
            self.assertIn("last reviewed on 2026-01-01", issue.message)
            self.assertIn("over the 30-day staleness window", issue.message)

    def test_a_malformed_reviewed_at_is_a_warning_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "a.md",
                front_matter="id: a\ntitle: A\nlang: en\nreviewed_at: not-a-date",
                body=(
                    "Some content about a benefits program for residents.\n\n"
                    "Additional details about eligibility and application deadlines "
                    "apply here.\n"
                ),
            )
            report = lint_corpus(corpus, max_age_days=30)
            self.assertEqual(report.warning_count, 1)
            self.assertIn("not a valid ISO date", report.issues[0].message)

    def test_staleness_runs_alongside_structural_errors(self):
        # Independent of the reachability checks, which are skipped when a
        # structural error stands elsewhere — staleness needs only front
        # matter, so it should not be held hostage by an unrelated bad file.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            write_doc(
                corpus, "good.md",
                front_matter="id: good\ntitle: Good\nlang: en",
                body="Fine content about a program.\n",
            )
            write_doc(corpus, "bad.md", front_matter="id: bad\ntitle: T", body="X.\n")
            report = lint_corpus(corpus, max_age_days=30)
            self.assertFalse(report.ok)  # the structural error still stands
            self.assertTrue(
                any("no 'reviewed_at'" in i.message for i in report.issues)
            )


class TestLintCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_cairn_lint_on_the_demo_corpus_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text(f'[corpus]\npath = "{DEMO.as_posix()}"\n', encoding="utf-8")
            code, out, err = self.run_cli(config, "lint")
            self.assertEqual(code, 0, err)
            self.assertIn("No issues found.", out)

    def test_cairn_lint_exits_nonzero_on_a_structural_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus"
            corpus.mkdir()
            write_doc(corpus, "bad.md", front_matter="id: b\ntitle: T", body="X.\n")
            config = Path(tmp) / "cairn.toml"
            config.write_text(f'[corpus]\npath = "{corpus.as_posix()}"\n', encoding="utf-8")
            code, out, err = self.run_cli(config, "lint")
            self.assertEqual(code, 1)
            self.assertIn("error(s)", out)

    def test_max_age_days_flag_is_off_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text(f'[corpus]\npath = "{DEMO.as_posix()}"\n', encoding="utf-8")
            code, out, err = self.run_cli(config, "lint")
            self.assertEqual(code, 0, err)
            self.assertIn("No issues found.", out)

    def test_max_age_days_flag_surfaces_missing_reviewed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text(f'[corpus]\npath = "{DEMO.as_posix()}"\n', encoding="utf-8")
            code, out, err = self.run_cli(config, "lint", "--max-age-days", "30")
            self.assertEqual(code, 0, err)  # warnings only, not errors
            self.assertIn("no 'reviewed_at'", out)

    def test_cairn_lint_does_not_require_an_index(self):
        # Unlike `ask`, `serve`, and `record`, `lint` reads the corpus only —
        # it must work with no `.cairn/index.json` anywhere.
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text(
                f'[corpus]\npath = "{DEMO.as_posix()}"\n'
                f'[index]\npath = "{(Path(tmp) / "nope.json").as_posix()}"\n',
                encoding="utf-8",
            )
            code, _, err = self.run_cli(config, "lint")
            self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
