"""`cairn config`: the effective configuration, reported against defaults."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.config_report import diff_from_defaults, render


class TestDiffFromDefaults(unittest.TestCase):
    def test_the_default_config_has_no_overrides(self):
        rows = diff_from_defaults(Config())
        self.assertTrue(rows)
        self.assertFalse(any(row.overridden for row in rows))
        self.assertIn("no overrides", render(rows))

    def test_an_overridden_field_is_reported_with_its_default(self):
        cfg = Config(threshold=0.2)
        rows = diff_from_defaults(cfg)
        by_key = {row.key: row for row in rows}
        self.assertTrue(by_key["threshold"].overridden)
        self.assertEqual(by_key["threshold"].effective, 0.2)
        self.assertEqual(by_key["threshold"].default, Config().threshold)
        self.assertFalse(by_key["max_passages"].overridden)

    def test_a_load_bearing_key_carries_a_rationale_pointer(self):
        rows = diff_from_defaults(Config(threshold=0.5))
        by_key = {row.key: row for row in rows}
        self.assertIsNotNone(by_key["threshold"].rationale)
        self.assertIn("DESIGN.md", by_key["threshold"].rationale)

    def test_render_marks_overridden_rows(self):
        text = render(diff_from_defaults(Config(max_passages=2)))
        self.assertIn("* max_passages = 2", text)
        self.assertIn("default: 1", text)
        # A field with no rationale entry (e.g. corpus_path) is not overridden
        # here, but still renders without crashing on a missing rationale.
        self.assertIn("corpus_path", text)

    def test_every_config_field_is_covered(self):
        from dataclasses import fields

        rows = diff_from_defaults(Config())
        self.assertEqual({row.key for row in rows}, {f.name for f in fields(Config)})


class TestConfigCli(unittest.TestCase):
    def run_cli(self, config_path: Path, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_cairn_config_with_no_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text("", encoding="utf-8")
            code, out, err = self.run_cli(config, "config")
            self.assertEqual(code, 0, err)
            self.assertIn("no overrides", out)

    def test_cairn_config_reports_a_real_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text("[retrieval]\nthreshold = 0.3\n", encoding="utf-8")
            code, out, err = self.run_cli(config, "config")
            self.assertEqual(code, 0, err)
            self.assertIn("* threshold = 0.3", out)

    def test_cairn_config_does_not_require_an_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cairn.toml"
            config.write_text(
                f'[index]\npath = "{Path(tmp) / "nope.json"}"\n', encoding="utf-8"
            )
            code, _, err = self.run_cli(config, "config")
            self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
