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
