"""`cairn record --diff-against`: an unscored preview of what recording would
produce, diffed against a bundle already on disk. Never writes anything."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.index import build_and_write, build_index
from cairn.record_diff import diff_against_bundle, render

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
QUESTIONS = ROOT / "plumbline" / "questions.toml"
COMMITTED_BUNDLE = ROOT / "plumbline" / "bundle"


class TestDiffAgainstBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_the_committed_bundle_matches_the_real_engine_right_now(self):
        # The strongest form of this test: not a fixture, the actual
        # committed evidence. If this ever fails, either the corpus or the
        # config has drifted from what was last recorded — which is exactly
        # what `cairn record` (unrun) would otherwise hide until the gate ran.
        diffs = diff_against_bundle(
            self.index, Config(), COMMITTED_BUNDLE, questions_path=QUESTIONS
        )
        self.assertEqual(diffs, (), diffs)
        self.assertIn("No difference", render(diffs))

    def test_a_changed_config_is_reported_as_changed_items(self):
        # A threshold this far off the calibrated default changes at least
        # one item's grounded/refused outcome, which changes response text.
        diffs = diff_against_bundle(
            self.index, Config(threshold=0.9), COMMITTED_BUNDLE, questions_path=QUESTIONS
        )
        self.assertTrue(diffs)
        self.assertTrue(all(d.kind == "changed" for d in diffs))
        text = render(diffs)
        self.assertIn("item(s) differ", text)
        self.assertIn("unscored preview", text)
        self.assertIn("plumbline-gate.sh", text)

    def test_a_missing_bundle_directory_is_all_additions(self):
        with tempfile.TemporaryDirectory() as tmp:
            diffs = diff_against_bundle(
                self.index, Config(), Path(tmp) / "nowhere", questions_path=QUESTIONS
            )
            self.assertTrue(diffs)
            self.assertTrue(all(d.kind == "added" for d in diffs))

    def test_a_question_dropped_from_the_set_is_reported_as_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            questions = Path(tmp) / "one.toml"
            questions.write_text(
                '[[item]]\nid = "solo"\nlang = "en"\nbehavior = "refuse"\n'
                'prompt = "Completely unrelated to anything here."\n',
                encoding="utf-8",
            )
            diffs = diff_against_bundle(
                self.index, Config(), COMMITTED_BUNDLE, questions_path=questions
            )
            kinds = {d.kind for d in diffs}
            self.assertIn("removed", kinds)
            self.assertNotIn("solo", {d.item_id for d in diffs if d.kind == "removed"})


class TestRecordDiffCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_diff_against_does_not_write_or_modify_a_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            index_path = workspace / "index.json"
            build_and_write(DEMO, index_path)
            config = workspace / "cairn.toml"
            config.write_text(
                f'[corpus]\npath = "{DEMO.as_posix()}"\n'
                f'[index]\npath = "{index_path.as_posix()}"\n',
                encoding="utf-8",
            )
            before = sorted(p.name for p in COMMITTED_BUNDLE.iterdir())
            code, out, err = self.run_cli(
                config, "record", "--diff-against", str(COMMITTED_BUNDLE),
                "--questions", str(QUESTIONS),
            )
            after = sorted(p.name for p in COMMITTED_BUNDLE.iterdir())
            self.assertEqual(code, 0, err)
            self.assertEqual(before, after, "the committed bundle must be untouched")
            self.assertIn("No difference", out)


if __name__ == "__main__":
    unittest.main()
