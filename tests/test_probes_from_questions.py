"""`probes_from_questions.py`: one place a question lives."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import probes_from_questions
from cairn.calibrate import load_probes

QUESTIONS = """
[[item]]
id = "p-001"
lang = "en"
behavior = "answer"
prompt = 'How do I apply for "CalFresh"?'
answering_sources = ["calfresh-en#2"]
source = "elicited"

[[item]]
id = "p-002"
lang = "es"
behavior = "refuse"
prompt = "¿Cuánto cuesta una licencia de perro?"
"""


class TestRender(unittest.TestCase):
    def test_round_trips_through_calibrate_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "questions.toml"
            q.write_text(QUESTIONS, encoding="utf-8")
            out = Path(tmp) / "probes.toml"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = probes_from_questions.main([str(q), "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("Wrote 2 probe(s)", stdout.getvalue())
            probes = load_probes(out)
            self.assertEqual(len(probes), 2)
            self.assertEqual(probes[0]["question"], 'How do I apply for "CalFresh"?')
            self.assertEqual(probes[0]["behavior"], "answer")
            self.assertEqual(probes[1]["lang"], "es")
            self.assertEqual(probes[1]["behavior"], "refuse")
            self.assertIn("do not edit", out.read_text(encoding="utf-8"))

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "questions.toml"
            q.write_text(QUESTIONS, encoding="utf-8")
            a, b = Path(tmp) / "a.toml", Path(tmp) / "b.toml"
            with contextlib.redirect_stdout(io.StringIO()):
                probes_from_questions.main([str(q), "-o", str(a)])
                probes_from_questions.main([str(q), "-o", str(b)])
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_bad_question_set_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "questions.toml"
            q.write_text('[[item]]\nid = "x"\nlang = "en"\nbehavior = "answer"\nprompt = "q"\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = probes_from_questions.main([str(q), "-o", str(Path(tmp) / "p.toml")])
            self.assertEqual(code, 1)
            self.assertIn("answering_sources", err.getvalue())


if __name__ == "__main__":
    unittest.main()
