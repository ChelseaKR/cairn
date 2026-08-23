"""Streaming: presentation only, and exactly so.

Every test here guards one clause of cairn/stream.py's contract. The two
byte-level ones — CLI output equals engine frames, server frames equal CLI
frames — are the reason the module takes an ``Answer`` rather than a
pipeline: there is exactly one place a frame can come from, so the terminal
and the socket cannot disagree the way two renderers once did.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.index import build_and_write, build_index
from cairn.stream import _chunks, events, format_sse, sse_stream

ROOT = Path(__file__).resolve().parent.parent

CORPUS = "corpus/demo"


class TestChunking(unittest.TestCase):
    def test_concatenation_is_the_text_byte_for_byte(self):
        cases = [
            "One sentence. Another! Arabic؟ Done.",
            "no terminator at all",
            "Trailing space. ",
            "\n\nleading blank lines\n\nmiddle.\n\ntail",
            "$212 per month. Each member adds $118.",
            "",
        ]
        for text in cases:
            with self.subTest(text=text[:24]):
                self.assertEqual("".join(_chunks(text)), text)

    def test_boundaries_only_after_terminators(self):
        chunks = _chunks("A first sentence. A second one follows here.")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith(". "))
        self.assertEqual(chunks[1], "A second one follows here.")

    def test_numbers_are_not_sentence_breaks(self):
        self.assertEqual(_chunks("Call 555-0142. Office hours apply."), [
            "Call 555-0142. ",
            "Office hours apply.",
        ])


class TestEventOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)

    def frames(self, question):
        answer = ask(question, self.index, Config()).answer
        return list(events(answer))

    def test_spans_precede_every_text_frame(self):
        kinds = [e["event"] for e in self.frames(
            "How much is the monthly grocery allowance for one person?")]
        self.assertIn("span", kinds)
        self.assertLess(kinds.index("span"), kinds.index("text"))

    def test_a_refusal_streams_without_spans(self):
        frames = self.frames("What is the capital of France?")
        kinds = [e["event"] for e in frames]
        self.assertNotIn("span", kinds)
        self.assertIn("text", kinds)
        joined = "".join(e["text"] for e in frames if e["event"] == "text")
        self.assertEqual(joined, ask(
            "What is the capital of France?", self.index, Config()).answer.text)

    def test_text_frames_reassemble_the_answer_exactly(self):
        for question in (
            "How much is the monthly grocery allowance for one person?",
            "¿Cuánto cubre la subvención de alivio de vivienda?",
            "ما المبلغ الذي تغطيه منحة إغاثة السكن؟",
            "How many programs have a monthly benefit over $100?",
        ):
            with self.subTest(question=question[:30]):
                frames = self.frames(question)
                joined = "".join(f["text"] for f in frames if f["event"] == "text")
                answer = ask(question, self.index, Config()).answer
                self.assertEqual(joined, answer.text)

    def test_span_carry_the_full_source_payload(self):
        frames = self.frames("How much does the GoPass cost per year?")
        span = next(f["source"] for f in frames if f["event"] == "span")
        self.assertIn("id", span)
        self.assertIn("lang", span)
        self.assertIn("dir", span)

    def test_two_runs_are_identical(self):
        question = "When is the deadline to apply for the housing grant?"
        answer = ask(question, self.index, Config()).answer
        first = [format_sse(e) for e in events(answer)]
        second = [format_sse(e) for e in events(answer)]
        self.assertEqual(first, second)


class TestSurfacesAgree(unittest.TestCase):
    """CLI --stream and the served endpoint emit byte-identical sequences."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.question = "How much is the monthly grocery allowance for one person?"
        # The CLI subprocess below reads an index off disk (read_index), not
        # the in-process one above (build_index) — an index this test does
        # not build itself and point --config at would leave the subprocess
        # depending on whichever .cairn/index.json happened to already exist
        # in the working directory it runs in, built or not, stale or not.
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._tmp.name)
        cls.config = cls.workspace / "cairn.toml"
        cls.config.write_text(
            f'[corpus]\npath = "{Path(CORPUS).resolve().as_posix()}"\n'
            f'[index]\npath = "{(cls.workspace / "index.json").as_posix()}"\n',
            encoding="utf-8",
        )
        build_and_write(CORPUS, cls.workspace / "index.json")
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def offline_frames(self):
        answer = ask(self.question, self.index, Config()).answer
        return "".join(sse_stream(answer))

    def test_cli_output_is_the_offline_stream(self):
        completed = subprocess.run(
            [sys.executable, "-m", "cairn", "--config", str(self.config),
             "ask", "--stream", self.question],
            cwd=self.workspace, env=self.env,
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(completed.stdout, self.offline_frames())

    def test_server_frames_match_and_declare_event_stream(self):
        import threading
        from http.server import ThreadingHTTPServer

        from cairn.server import build_handler

        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), build_handler(Config(), self.index, quiet=True)
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/ask",
                data=json.dumps(
                    {"question": self.question, "lang": "en", "stream": True}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request) as response:
                self.assertTrue(response.headers["Content-Type"].startswith(
                    "text/event-stream"))
                body = response.read().decode("utf-8")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
        self.assertEqual(body, self.offline_frames())


if __name__ == "__main__":
    unittest.main()
