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


ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "corpus" / "pilot-usagov"


def generated_part(text: str) -> str:
    """A probe file with its leading authored comment block removed.

    `corpus/pilot-usagov/probes.toml` is the shape this module's docstring
    warns about handled properly: an authored header saying what the file is
    and where the run that used it is written up, and below it a region that
    is generated and nothing else. Splitting on the first non-comment line is
    what makes the second half comparable byte for byte without the first half
    having to be regenerable.
    """
    lines = text.split("\n")
    start = 0
    while start < len(lines) and (
            lines[start].startswith("#") or not lines[start].strip()):
        start += 1
    return "\n".join(lines[start:])


class TestTheCommittedPilotProbesAreDerived(unittest.TestCase):
    """The duplication this module was written to remove, still committed.

    The docstring above says the usa.gov pilot "kept `probes.toml` and
    `questions.toml` side by side and typed every question twice, which is two
    files that will disagree the day one is edited", and that this script
    "writes the first from the second, so there is one place a question
    lives". The script was written; `corpus/pilot-usagov/probes.toml` stayed
    the hand-typed twin, and nothing compared the two. They happened to still
    agree on all sixteen questions, which is the only reason this reads as a
    gate being added rather than a drift being found.
    """

    def test_the_generated_region_is_what_the_question_set_produces(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "probes.toml"
            with contextlib.redirect_stdout(io.StringIO()):
                code = probes_from_questions.main(
                    [str(PILOT / "questions.toml"), "-o", str(out)])
            self.assertEqual(code, 0)
            fresh = generated_part(out.read_text(encoding="utf-8"))
        committed = generated_part(
            (PILOT / "probes.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            committed, fresh,
            "corpus/pilot-usagov/probes.toml is not what its question set "
            "derives to; run `python3 probes_from_questions.py "
            "corpus/pilot-usagov/questions.toml -o "
            "corpus/pilot-usagov/probes.toml` and restore the authored header")

    def test_the_authored_header_says_the_rest_is_generated(self):
        # Without this the split above is a silent contract: a reader editing
        # a probe has to be told, in the file, that the edit will be
        # overwritten and that the gate will catch it first.
        header = (PILOT / "probes.toml").read_text(encoding="utf-8")
        header = header[:header.index("[[probe]]")]
        self.assertIn("GENERATED", header)
        self.assertIn("probes_from_questions.py", header)
        self.assertIn("questions.toml", header)

    def test_the_committed_probes_still_load(self):
        self.assertEqual(len(load_probes(PILOT / "probes.toml")), 16)


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
