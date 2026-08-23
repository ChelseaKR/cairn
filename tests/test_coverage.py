"""`cairn record --coverage`: which corpus passages the evidence question set
ever exercises. Read-only, writes no bundle, not part of audited evidence."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.coverage import coverage_report, render
from cairn.index import build_index

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
QUESTIONS = ROOT / "plumbline" / "questions.toml"


class TestCoverageReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_it_counts_against_the_real_question_set(self):
        report = coverage_report(self.index, Config(), questions_path=QUESTIONS)
        self.assertGreater(report.question_count, 0)
        self.assertEqual(report.passage_count, self.index.passage_count)
        self.assertTrue(report.reached_counts, "the real question set reaches something")
        self.assertLessEqual(len(report.reached_counts), report.passage_count)
        # Every reached id is a real passage id, and nothing is double-listed
        # between reached and unreached.
        all_ids = {p.passage_id for p in self.index.passages}
        self.assertTrue(set(report.reached_counts) <= all_ids)
        self.assertTrue(set(report.unreached) <= all_ids)
        self.assertEqual(set(report.reached_counts) & set(report.unreached), set())
        self.assertEqual(
            set(report.reached_counts) | set(report.unreached), all_ids,
            "every passage is accounted for as reached or unreached, no third state",
        )

    def test_a_question_set_that_asks_nothing_reaches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "off_topic.toml"
            empty.write_text(
                '[[item]]\nid = "x"\nlang = "en"\nbehavior = "refuse"\n'
                'prompt = "Completely unrelated to any of this."\n',
                encoding="utf-8",
            )
            report = coverage_report(self.index, Config(), questions_path=empty)
            self.assertEqual(report.reached_counts, {})
            self.assertEqual(len(report.unreached), report.passage_count)

    def test_render_lists_unreached_passages(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "off_topic.toml"
            empty.write_text(
                '[[item]]\nid = "x"\nlang = "en"\nbehavior = "refuse"\n'
                'prompt = "Completely unrelated to any of this."\n',
                encoding="utf-8",
            )
            report = coverage_report(self.index, Config(), questions_path=empty)
            text = render(report)
            self.assertIn("never appeared in any accepted", text)
            self.assertIn(report.unreached[0], text)

    def test_render_when_everything_is_reached(self):
        # Synthesize the all-reached branch directly rather than relying on
        # the real question set happening to reach every passage.
        from cairn.coverage import CoverageReport

        report = CoverageReport(
            question_count=1, passage_count=1, reached_counts={"a#1": 1}, unreached=()
        )
        self.assertIn("Every passage was reached", render(report))


class TestCoverageCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_record_coverage_does_not_write_a_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            index_path = workspace / "index.json"
            build_index(DEMO)
            from cairn.index import build_and_write

            build_and_write(DEMO, index_path)
            config = workspace / "cairn.toml"
            config.write_text(
                f'[corpus]\npath = "{DEMO.as_posix()}"\n'
                f'[index]\npath = "{index_path.as_posix()}"\n',
                encoding="utf-8",
            )
            out_dir = workspace / "bundle-should-not-exist"
            code, out, err = self.run_cli(
                config, "record", "--coverage",
                "--questions", str(QUESTIONS), "--out", str(out_dir),
            )
            self.assertEqual(code, 0, err)
            self.assertIn("question(s) exercised", out)
            self.assertFalse(out_dir.exists(), "--coverage must not write a bundle")


if __name__ == "__main__":
    unittest.main()
