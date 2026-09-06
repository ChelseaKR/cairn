"""`cairn calibrate`: check retrieval.threshold against a real probe set.

DESIGN.md's calibration note says the threshold must be re-checked against
probe questions when the corpus changes; this is that re-check as a tool.
Advisory — never edits cairn.toml — but the CLI exit code is meaningful:
1 when the configured threshold actually misclassifies a probe, or when the
probe set cannot vouch for it at all.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.calibrate import CalibrationError, calibrate, load_probes, render
from cairn.cli import main
from cairn.config import Config
from cairn.index import build_and_write, build_index

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
EXAMPLE_PROBES = ROOT / "docs" / "calibration-probes.example.toml"


def write_probes(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class TestLoadProbes(unittest.TestCase):
    def test_the_example_probe_file_loads(self):
        probes = load_probes(EXAMPLE_PROBES)
        self.assertGreaterEqual(len(probes), 4)
        self.assertTrue(all(p["behavior"] in ("answer", "refuse") for p in probes))

    def test_a_missing_file_is_an_error(self):
        with self.assertRaises(CalibrationError):
            load_probes("/nonexistent/probes.toml")

    def test_no_probe_entries_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(Path(tmp), "empty.toml", "# nothing here\n")
            with self.assertRaises(CalibrationError):
                load_probes(path)

    def test_a_missing_question_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(
                Path(tmp), "bad.toml", '[[probe]]\nbehavior = "answer"\n'
            )
            with self.assertRaises(CalibrationError):
                load_probes(path)

    def test_an_invalid_behavior_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(
                Path(tmp), "bad.toml",
                '[[probe]]\nquestion = "x"\nbehavior = "maybe"\n',
            )
            with self.assertRaises(CalibrationError):
                load_probes(path)

    def test_a_non_string_lang_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(
                Path(tmp), "bad.toml",
                '[[probe]]\nquestion = "x"\nbehavior = "answer"\nlang = 5\n',
            )
            with self.assertRaises(CalibrationError):
                load_probes(path)


class TestCalibrate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_the_example_probes_pass_at_the_shipped_default(self):
        report = calibrate(self.index, Config(), EXAMPLE_PROBES)
        self.assertTrue(report.safe, report.misclassified)
        self.assertEqual(report.misclassified, ())

    def test_worst_and_best_scores_are_computed_correctly(self):
        report = calibrate(self.index, Config(), EXAMPLE_PROBES)
        answer_scores = [r.top_score for r in report.answer_probes]
        refuse_scores = [r.top_score for r in report.refuse_probes]
        self.assertEqual(report.worst_answer_score, min(answer_scores))
        self.assertEqual(report.best_refuse_score, max(refuse_scores))
        self.assertAlmostEqual(
            report.gap, report.worst_answer_score - report.best_refuse_score
        )

    def test_suggested_threshold_is_the_midpoint_of_the_gap(self):
        report = calibrate(self.index, Config(), EXAMPLE_PROBES)
        self.assertAlmostEqual(
            report.suggested_threshold,
            (report.worst_answer_score + report.best_refuse_score) / 2,
        )

    def test_a_too_strict_threshold_misclassifies_answer_probes(self):
        report = calibrate(self.index, Config(threshold=0.99), EXAMPLE_PROBES)
        self.assertFalse(report.safe)
        self.assertTrue(report.misclassified)
        self.assertTrue(all(r.behavior == "answer" for r in report.misclassified))
        # The gap itself doesn't depend on the configured threshold.
        self.assertIsNotNone(report.gap)
        self.assertGreater(report.gap, 0)

    def test_a_too_loose_threshold_misclassifies_refuse_probes(self):
        report = calibrate(self.index, Config(threshold=0.001), EXAMPLE_PROBES)
        self.assertFalse(report.safe)
        self.assertTrue(any(r.behavior == "refuse" for r in report.misclassified))

    def test_only_answer_probes_gives_no_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(
                Path(tmp), "answer_only.toml",
                '[[probe]]\nquestion = '
                '"How much is the monthly grocery allowance for one person?"\n'
                'behavior = "answer"\n',
            )
            report = calibrate(self.index, Config(), path)
            self.assertIsNone(report.gap)
            self.assertIsNone(report.suggested_threshold)
            self.assertIsNone(report.best_refuse_score)
            self.assertFalse(report.safe, "no gap means the probe set cannot vouch for it")

    def test_render_reports_no_separating_threshold(self):
        # Construct a report by hand where the bands overlap, rather than
        # hunting for real questions that happen to tie — the rendering
        # logic is what's under test, not the scorer.
        from cairn.calibrate import CalibrationReport, ProbeResult

        report = CalibrationReport(
            threshold=0.2,
            results=(
                ProbeResult("a", "answer", None, 0.1, "refuse", False),
                ProbeResult("b", "refuse", None, 0.3, "answer", False),
            ),
        )
        self.assertIsNotNone(report.gap)
        self.assertLessEqual(report.gap, 0)
        text = render(report)
        self.assertIn("NO SEPARATING THRESHOLD", text)

    def test_render_lists_every_probe_and_the_verdict(self):
        report = calibrate(self.index, Config(), EXAMPLE_PROBES)
        text = render(report)
        for r in report.results:
            self.assertIn(r.question, text)
        self.assertIn("classifies every probe correctly", text)


class TestCalibrateCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def _config(self, workspace: Path, **retrieval) -> Path:
        index_path = workspace / "index.json"
        build_and_write(DEMO, index_path)
        lines = [
            f'[corpus]\npath = "{DEMO.as_posix()}"\n'
            f'[index]\npath = "{index_path.as_posix()}"\n'
        ]
        if retrieval:
            lines.append("[retrieval]\n")
            lines += [f"{k} = {v}\n" for k, v in retrieval.items()]
        config = workspace / "cairn.toml"
        config.write_text("".join(lines), encoding="utf-8")
        return config

    def test_cairn_calibrate_exits_zero_when_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            code, out, err = self.run_cli(
                config, "calibrate", "--probes", str(EXAMPLE_PROBES)
            )
            self.assertEqual(code, 0, err)
            self.assertIn("classifies every probe correctly", out)

    def test_cairn_calibrate_exits_nonzero_when_unsafe(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp), threshold=0.99)
            code, out, err = self.run_cli(
                config, "calibrate", "--probes", str(EXAMPLE_PROBES)
            )
            self.assertEqual(code, 1, err)
            self.assertIn("MISCLASSIFIED", out)

    def test_a_malformed_probe_file_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            bad = write_probes(Path(tmp), "bad.toml", "# empty\n")
            code, out, err = self.run_cli(config, "calibrate", "--probes", str(bad))
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("no [[probe]] entries", err)

    def test_calibrate_requires_an_index_like_ask_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config = workspace / "cairn.toml"
            config.write_text(
                f'[corpus]\npath = "{DEMO.as_posix()}"\n'
                f'[index]\npath = "{(workspace / "nope.json").as_posix()}"\n',
                encoding="utf-8",
            )
            code, out, err = self.run_cli(
                config, "calibrate", "--probes", str(EXAMPLE_PROBES)
            )
            self.assertEqual(code, 1)
            self.assertIn("run `cairn index`", err)


if __name__ == "__main__":
    unittest.main()


TABLE_PROBES = """
[[probe]]
question = "How many programs pay more than $100 a month?"
behavior = "answer"

[[probe]]
question = "How much is the monthly grocery allowance for one person?"
behavior = "answer"

[[probe]]
question = "Can you help me renew my drivers license?"
behavior = "refuse"

[[probe]]
question = "What vaccinations does my dog need?"
behavior = "refuse"
"""


class TestToolAnsweredProbes(unittest.TestCase):
    """Issue #91: a probe no threshold decided must not set the threshold band.

    The count tool answers before retrieval runs, so its probe has no score.
    Recording that absence as `0.0` made a correctly-answered probe the worst
    'answer' probe in the set, drove `gap` negative, and made `render` print
    `NO SEPARATING THRESHOLD` and "classifies every probe correctly" in the
    same run — while withholding the suggested threshold that is the tool's
    entire output.

    Scored against the demo corpus rather than hand-built, deliberately: the
    existing renderer tests build a `CalibrationReport` directly, which is
    why this was invisible to them.
    """

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(Path(tmp), "table.toml", TABLE_PROBES)
            return calibrate(self.index, Config(), path)

    def test_the_counting_probe_is_answered_and_carries_no_score(self):
        report = self.report()
        probe = next(r for r in report.results if r.question.startswith("How many"))
        self.assertEqual(probe.outcome, "answer")
        self.assertTrue(probe.correct)
        self.assertIsNone(probe.top_score)
        self.assertEqual(report.tool_probes, (probe,))

    def test_it_does_not_drag_the_band_negative(self):
        report = self.report()
        self.assertIsNotNone(report.gap)
        self.assertGreater(report.gap, 0)
        self.assertIsNotNone(report.suggested_threshold)
        # The band is set by the other 'answer' probe — the one a threshold
        # actually decided. Derived, not pinned to a rounded literal.
        scored = next(
            r for r in report.answer_probes if r.top_score is not None
        )
        self.assertEqual(report.worst_answer_score, scored.top_score)

    def test_the_report_does_not_contradict_itself(self):
        report = self.report()
        text = render(report)
        self.assertNotIn("NO SEPARATING THRESHOLD", text)
        self.assertIn("classifies every probe correctly", text)
        self.assertIn("Suggested threshold", text)

    def test_the_row_says_n_a_rather_than_a_score_of_zero(self):
        text = render(self.report())
        line = next(ln for ln in text.splitlines() if "How many" in ln)
        self.assertIn("score=  n/a", line)
        self.assertNotIn("score=0.000", line)
        self.assertIn("excluded from the band", text)

    def test_a_probe_that_really_scored_zero_still_counts(self):
        # The negative control. `top_score is None` must mean "never scored",
        # never "scored badly": a genuine no-overlap probe still enters the
        # arithmetic as 0.0 and still drags the band, which is correct.
        body = (
            '[[probe]]\nquestion = "zzzzqqqq wwwwxxxx"\nbehavior = "answer"\n\n'
            '[[probe]]\nquestion = "What vaccinations does my dog need?"\n'
            'behavior = "refuse"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_probes(Path(tmp), "zero.toml", body)
            report = calibrate(self.index, Config(), path)
        probe = next(r for r in report.results if r.question.startswith("zzzz"))
        self.assertEqual(probe.top_score, 0.0)
        self.assertEqual(report.tool_probes, ())
        self.assertIsNotNone(report.gap)
        self.assertLessEqual(report.gap, 0)
