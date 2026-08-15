"""CLI behavior: exit codes, reporting, JSON output, milestone stubs."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cairn.cli import build_parser, main
from cairn.language import POP_DIRECTIONAL_ISOLATE

ROOT = Path(__file__).resolve().parent.parent


class CliHarness(unittest.TestCase):
    """Runs the CLI in-process against a temp config + index."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.index_path = Path(cls._tmp.name) / "index.json"
        cls.config_path = Path(cls._tmp.name) / "cairn.toml"
        cls.config_path.write_text(
            "[corpus]\n"
            f'path = "{ROOT / "corpus" / "demo"}"\n'
            "[index]\n"
            f'path = "{cls.index_path}"\n',
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(self.config_path), *argv])
        return code, out.getvalue(), err.getvalue()


class TestCli(CliHarness):
    def test_01_index_reports_counts_and_path(self):
        code, out, _ = self.run_cli("index")
        self.assertEqual(code, 0)
        self.assertIn("Indexed 40 passages from 10 documents", out)
        self.assertIn("(10 marked synthetic)", out)
        self.assertIn(str(self.index_path), out)

    def test_02_ask_grounded_json(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "How much is the monthly grocery allowance for one person?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "grounded")
        self.assertIn("$212", payload["text"])
        self.assertTrue(payload["sources"])

    def test_03_ask_refusal_exits_zero_no_sources_section(self):
        self.run_cli("index")
        code, out, _ = self.run_cli("ask", "Can you help me renew my drivers license?")
        self.assertEqual(code, 0, "refusal is a first-class outcome, not an error")
        self.assertNotIn("Sources:", out)

    def test_ask_without_index_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.toml"
            cfg.write_text(
                f'[corpus]\npath = "{ROOT / "corpus" / "demo"}"\n'
                f'[index]\npath = "{Path(tmp) / "missing.json"}"\n',
                encoding="utf-8",
            )
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--config", str(cfg), "ask", "anything"])
            self.assertEqual(code, 1)
            self.assertIn("cairn index", err.getvalue())

    def test_04_ask_explain_reports_the_trace_alongside_the_answer(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--explain", "How much is the monthly grocery allowance for one person?"
        )
        self.assertEqual(code, 0)
        self.assertIn("Attempt 1 (restricted to 'en')", out)
        self.assertIn("Stage 1 - retrieval:", out)
        self.assertIn("Stage 2 - answer:", out)
        self.assertIn("Verdict: GROUNDED", out)
        self.assertIn("Sources:", out, "the answer itself is still printed")
        self.assertIn(str(self.index_path), out, "the trace names the index it read")

    def test_05_ask_explain_json_carries_candidates_and_diagnosis(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "--explain", "Can you help me renew my drivers license?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "refusal")
        explain = payload["explain"]
        self.assertEqual(explain["threshold"], 0.165)
        self.assertTrue(all(not c["accepted"] for c in explain["candidates"]))
        self.assertEqual(explain["diagnosis"]["blame"], "retrieval")
        self.assertFalse(explain["diagnosis"]["grounded"])
        self.assertEqual(
            [s["stage"] for s in explain["diagnosis"]["stages"]], ["retrieval", "answer"]
        )
        self.assertEqual(explain["language"]["lang"], "en")
        self.assertEqual([a["scope"] for a in explain["attempts"]], ["language", "corpus"])
        self.assertFalse(explain["cross_language"])

    def test_06_explain_is_opt_in(self):
        self.run_cli("index")
        _, plain, _ = self.run_cli("ask", "--json", "How much does the GoPass cost per year?")
        self.assertNotIn("explain", json.loads(plain))

    def test_07_index_reports_the_languages_it_indexed(self):
        _, out, _ = self.run_cli("index")
        self.assertIn("3 languages [ar, en, es]", out)

    def test_08_lang_selects_the_answer_language(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "--lang", "ar", "How much is the grocery allowance?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["lang"], "ar")
        self.assertEqual(payload["dir"], "rtl")

    def test_09_rtl_output_isolates_latin_source_ids(self):
        self.run_cli("index")
        _, out, _ = self.run_cli("ask", "كم تحصل الأسرة المكونة من شخص واحد شهريًا؟")
        self.assertIn("المصادر:", out, "the sources heading speaks the answer language")
        self.assertIn(POP_DIRECTIONAL_ISOLATE, out, "Latin ids are bidi-isolated")

    def test_10_an_unsupported_language_is_an_error_not_a_bad_answer(self):
        self.run_cli("index")
        code, out, err = self.run_cli("ask", "--lang", "tlh", "anything")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("unsupported language", err)

    def test_11_serve_binds_to_this_machine_only_by_default(self):
        # A demo server that listens on every interface by default is a demo
        # server someone accidentally exposes. The behaviour of the server
        # itself is covered in tests/test_ui.py.
        args = build_parser().parse_args(["serve"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertIs(
            args.func.__wrapped__ if hasattr(args.func, "__wrapped__") else args.func, args.func
        )


if __name__ == "__main__":
    unittest.main()
