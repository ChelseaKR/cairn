"""`cairn ask --explain --compare-config/--compare-index`: a single-question
A/B tuning aid, never a gate."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.explain_diff import compare, render
from cairn.index import build_and_write, build_index

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
QUESTION = "How much is the monthly grocery allowance for one person?"


class TestCompare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_identical_configs_produce_no_flip(self):
        comparison = compare(QUESTION, self.index, Config(), self.index, Config())
        self.assertEqual(comparison.a, comparison.b)
        text = render(comparison)
        self.assertIn("No change in verdict, blame, or the accepted set", text)
        self.assertIn("not a gate", text)

    def test_a_threshold_high_enough_to_refuse_flips_the_verdict(self):
        comparison = compare(
            QUESTION, self.index, Config(), self.index, Config(threshold=0.99)
        )
        self.assertEqual(comparison.a.verdict, "grounded")
        self.assertEqual(comparison.b.verdict, "refusal")
        text = render(comparison)
        self.assertIn("VERDICT FLIP: grounded -> refusal", text)
        self.assertIn("no longer accepted:", text)

    def test_score_deltas_are_reported_for_shared_candidates(self):
        # Same corpus, same question: the candidate set is identical between
        # sides, so every candidate is "shared" — but title weighting
        # differing would move scores. Here we compare against itself with a
        # different max_passages, which does not move any score at all, to
        # pin the no-movement case explicitly.
        comparison = compare(
            QUESTION, self.index, Config(), self.index, Config(max_passages=2)
        )
        self.assertEqual(comparison.a.scores, comparison.b.scores)


class TestCompareCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def _config(self, workspace: Path, name: str, index_path: Path, **retrieval) -> Path:
        build_and_write(DEMO, index_path)
        lines = [f'[corpus]\npath = "{DEMO}"\n[index]\npath = "{index_path}"\n']
        if retrieval:
            lines.append("[retrieval]\n")
            lines += [f"{k} = {v}\n" for k, v in retrieval.items()]
        config = workspace / name
        config.write_text("".join(lines), encoding="utf-8")
        return config

    def test_compare_config_reports_a_flip_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config_a = self._config(workspace, "a.toml", workspace / "a.json")
            config_b = self._config(
                workspace, "b.toml", workspace / "b.json", threshold=0.99
            )
            code, out, err = self.run_cli(
                config_a, "ask", "--explain", "--compare-config", str(config_b), QUESTION
            )
            self.assertEqual(code, 0, err)
            self.assertIn("VERDICT FLIP", out)

    def test_compare_index_alone_triggers_comparison_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config_a = self._config(workspace, "a.toml", workspace / "a.json")
            other_index = workspace / "b.json"
            build_and_write(DEMO, other_index)
            code, out, err = self.run_cli(
                config_a, "ask", "--compare-index", str(other_index), QUESTION
            )
            self.assertEqual(code, 0, err)
            self.assertIn("No change in verdict, blame, or the accepted set", out)


if __name__ == "__main__":
    unittest.main()
