"""`cairn/refusal_stats.py`: the write side (`RefusalCounter`), the read side
(`report`/`render`), the classification it counts (`explain.refusal_reason`),
and the server/CLI wiring around both.

The recurring assertion, as with `tests/test_network.py`: with
`--refusal-stats` unset, nothing about this feature is reachable at all —
no file, no counting, no change to a refusal's response.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.engine import ask
from cairn.explain import refusal_reason
from cairn.index import build_index
from cairn.refusal_stats import RefusalCounter, RefusalReport, RefusalStatsError, render, report
from cairn.server import build_handler

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"


class TestRefusalCounter(unittest.TestCase):
    def test_a_missing_file_starts_at_zero(self):
        with tempfile.TemporaryDirectory() as d:
            counter = RefusalCounter(Path(d) / "does-not-exist-yet.json")
            self.assertEqual(counter.snapshot(), {})

    def test_recording_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            counter = RefusalCounter(path)
            counter.record("en", "below-threshold")
            self.assertTrue(path.is_file())
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, {"en": {"below-threshold": 1}})

    def test_the_same_lang_and_code_accumulate(self):
        with tempfile.TemporaryDirectory() as d:
            counter = RefusalCounter(Path(d) / "stats.json")
            counter.record("en", "below-threshold")
            counter.record("en", "below-threshold")
            counter.record("en", "below-threshold")
            self.assertEqual(counter.snapshot(), {"en": {"below-threshold": 3}})

    def test_different_languages_and_codes_are_counted_separately(self):
        with tempfile.TemporaryDirectory() as d:
            counter = RefusalCounter(Path(d) / "stats.json")
            counter.record("en", "below-threshold")
            counter.record("es", "no-lexical-overlap")
            counter.record("en", "no-lexical-overlap")
            self.assertEqual(
                counter.snapshot(),
                {
                    "en": {"below-threshold": 1, "no-lexical-overlap": 1},
                    "es": {"no-lexical-overlap": 1},
                },
            )

    def test_a_new_counter_reloads_what_an_earlier_one_wrote(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            RefusalCounter(path).record("en", "below-threshold")
            reloaded = RefusalCounter(path)
            self.assertEqual(reloaded.snapshot(), {"en": {"below-threshold": 1}})
            reloaded.record("en", "below-threshold")
            self.assertEqual(reloaded.snapshot(), {"en": {"below-threshold": 2}})

    def test_only_a_directory_that_does_not_exist_yet_is_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nested" / "dir" / "stats.json"
            RefusalCounter(path).record("en", "below-threshold")
            self.assertTrue(path.is_file())

    def test_a_file_that_is_not_json_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            path.write_text("not json at all {", encoding="utf-8")
            with self.assertRaises(RefusalStatsError):
                RefusalCounter(path)

    def test_a_json_file_that_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(RefusalStatsError):
                RefusalCounter(path)

    def test_a_language_whose_value_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            path.write_text('{"en": 3}', encoding="utf-8")
            with self.assertRaises(RefusalStatsError):
                RefusalCounter(path)


class TestReport(unittest.TestCase):
    def test_a_missing_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RefusalStatsError):
                report(Path(d) / "never-written.json")

    def test_the_error_names_the_flag_that_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RefusalStatsError) as ctx:
                report(Path(d) / "never-written.json")
            self.assertIn("--refusal-stats", str(ctx.exception))

    def test_totals_sum_every_language_and_code(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            counter = RefusalCounter(path)
            counter.record("en", "below-threshold")
            counter.record("en", "no-lexical-overlap")
            counter.record("es", "no-passages-in-language")
            rep = report(path)
            self.assertEqual(rep.total, 3)
            self.assertEqual(rep.by_language["en"]["below-threshold"], 1)


class TestRender(unittest.TestCase):
    def test_zero_refusals_says_so_plainly(self):
        empty = RefusalReport(total=0, by_language={})
        self.assertEqual(render(empty), "No refusals recorded yet.")

    def test_the_total_and_every_row_appear(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            counter = RefusalCounter(path)
            counter.record("en", "below-threshold")
            counter.record("es", "no-passages-in-language")
            text = render(report(path))
            self.assertIn("2 refusal(s) recorded", text)
            self.assertIn("en", text)
            self.assertIn("below-threshold", text)
            self.assertIn("es", text)
            self.assertIn("no-passages-in-language", text)

    def test_never_shows_question_text(self):
        # There is none to show — the point under test is just that render()
        # only ever draws from lang/code/count, nothing else.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            RefusalCounter(path).record("en", "below-threshold")
            text = render(report(path))
            self.assertNotIn("question", text.lower().split("reason codes")[0])


class TestRefusalReason(unittest.TestCase):
    """`cairn.explain.refusal_reason` — the classification this whole module
    counts, isolated from the counting."""

    def setUp(self):
        self.index = build_index(DEMO)
        self.cfg = Config()

    def test_a_below_threshold_refusal_is_classified(self):
        result = ask("purple elephants juggling unicycles", self.index, self.cfg, lang="en")
        self.assertEqual(result.answer.kind, "refusal")
        code = refusal_reason(result.answer.trace)
        self.assertIn(
            code, ("below-threshold", "no-lexical-overlap", "no-passages-in-language")
        )

    def test_a_grounded_answer_is_never_asked_to_classify(self):
        # refusal_reason() is documented as meaningful only when
        # trace.accepted is empty; a grounded trace's code is
        # "passages-accepted", not a refusal reason, and callers (server.py)
        # only ever call this behind `result.answer.kind == "refusal"`.
        result = ask("How much is the grocery allowance?", self.index, self.cfg, lang="en")
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual(refusal_reason(result.answer.trace), "passages-accepted")


class RefusalStatsServerHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.stats_path = Path(cls._tmp.name) / "stats.json"
        cls.cfg = Config()
        cls.index = build_index(DEMO)
        cls.counter = RefusalCounter(cls.stats_path)
        handler = build_handler(cls.cfg, cls.index, quiet=True, refusal_counter=cls.counter)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def post_json(self, payload):
        request = urllib.request.Request(
            self.base + "/ask",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))


class TestServerRecordsRefusalsOnly(RefusalStatsServerHarness):
    def test_a_refusal_is_counted(self):
        before = self.counter.snapshot()
        result = self.post_json({"question": "purple elephants juggling unicycles"})
        self.assertEqual(result.get("kind"), "refusal")
        after = self.counter.snapshot()
        before_total = sum(n for c in before.values() for n in c.values())
        after_total = sum(n for c in after.values() for n in c.values())
        self.assertEqual(after_total, before_total + 1)

    def test_a_grounded_answer_is_not_counted(self):
        before = self.counter.snapshot()
        result = self.post_json({"question": "How much is the grocery allowance?"})
        self.assertEqual(result.get("kind"), "grounded")
        after = self.counter.snapshot()
        self.assertEqual(before, after)

    def test_the_response_body_is_unaffected_by_stats_being_on(self):
        # Enabling --refusal-stats changes nothing a client can observe.
        result = self.post_json({"question": "purple elephants juggling unicycles"})
        self.assertNotIn("stats", result)
        self.assertNotIn("refusal_stats", result)


class TestNoCounterIsUnchanged(unittest.TestCase):
    """The default: no refusal_counter at all, nothing new happens."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.index = build_index(DEMO)
        handler = build_handler(cls.cfg, cls.index, quiet=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_a_refusal_with_no_counter_configured_just_answers(self):
        request = urllib.request.Request(
            self.base + "/ask",
            data=json.dumps({"question": "purple elephants juggling unicycles"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(result.get("kind"), "refusal")


class TestCliRefusalsCommand(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_reports_a_written_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.json"
            RefusalCounter(path).record("en", "below-threshold")
            code, out, _ = self.run_cli("refusals", str(path))
            self.assertEqual(code, 0)
            self.assertIn("1 refusal(s) recorded", out)

    def test_a_missing_file_is_a_clean_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "never-written.json"
            code, out, err = self.run_cli("refusals", str(path))
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("cairn: error:", err)
            self.assertIn("--refusal-stats", err)


if __name__ == "__main__":
    unittest.main()
