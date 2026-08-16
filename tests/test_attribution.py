"""Right document, wrong paragraph — the failure every other check passes.

An answer composed from the wrong paragraph of the right document is
grounded, correctly cited, supported by the passage it points at, in the right
language, and not a refusal. Cairn found one (`ck-022`), could not express it
in any suite the pinned harness had, said so, and Plumbline built
`passage_attribution`. This file covers Cairn's half of that suite: the
authored ground truth it reads, and the one item it currently fails.

Everything here is offline and needs no harness. The suite runs at gate time;
these are the checks that keep its inputs honest before anyone waits on a
fetch, plus a pinned record of the known failure so that a corpus or tokenizer
change which moves it fails a test and names what moved.
"""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.index import build_index
from cairn.record import RecordError, load_questions

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "plumbline" / "questions.toml"
BUNDLE = ROOT / "plumbline" / "bundle"
DEMO = ROOT / "corpus" / "demo"
CFG = Config()

# The known wrong-paragraph case, pinned. `ck-022` asks about the housing
# grant's amount with a planted "$10,000" in it; the answer comes back from
# the deadline paragraph, because "pays out" in the question meets "until the
# year's funds run out" and "out" is rare enough in a ten-document corpus that
# document frequency rates it as informative. DESIGN.md carries the term
# evidence and why neither available fix is taken.
WRONG_PARAGRAPH = "housing-relief-en#4"
RIGHT_PARAGRAPH = "housing-relief-en#2"


def passage_id(source_id: str) -> str:
    """The inverse of `cairn.answer.citation_marker`: a bundle source id back
    to the Cairn passage id it names."""
    head, _, ordinal = source_id.rpartition(".")
    return f"{head}#{ordinal}"


def questions():
    return tomllib.loads(QUESTIONS.read_text(encoding="utf-8"))["item"]


def items():
    return [json.loads(line)
            for line in (BUNDLE / "items.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


class TestTheAuthoredGroundTruth(unittest.TestCase):
    """`answering_sources` is the only field in the question set that says
    what retrieval *should* have returned. It is authored, so it is the one
    thing here that can be wrong in a way no measurement will catch — which is
    why it is checked for the things that can be checked."""

    @classmethod
    def setUpClass(cls):
        cls.questions = questions()
        cls.passages = {p.passage_id for p in build_index(DEMO).passages}

    def test_every_answer_item_declares_one(self):
        undeclared = [q["id"] for q in self.questions
                      if q["behavior"] == "answer" and not q.get("answering_sources")]
        self.assertEqual(undeclared, [], "an undeclared item is reported "
                                         "unverifiable, and a question set full "
                                         "of those is a check that is not running")

    def test_no_refusal_declares_one(self):
        declared = [q["id"] for q in self.questions
                    if q["behavior"] == "refuse" and q.get("answering_sources")]
        self.assertEqual(declared, [], "nothing answers a question that should "
                                       "not be answered")

    def test_every_declared_passage_exists_in_the_corpus(self):
        for question in self.questions:
            for source in question.get("answering_sources", []):
                with self.subTest(item=question["id"], source=source):
                    self.assertIn(passage_id(source), self.passages)

    def test_the_declared_passage_contains_the_expected_answer_s_numbers(self):
        # The cheapest possible check on human ground truth, and it caught
        # nothing — which is the result worth recording. A declaration whose
        # passage does not contain the amount the item expects is either the
        # wrong passage or the wrong expectation.
        passages = {p.passage_id: p.text for p in build_index(DEMO).passages}
        exercised = []
        for question in self.questions:
            declared = question.get("answering_sources") or []
            expected = question.get("expected") or ""
            numbers = [word for word in expected.replace(",", "").split()
                       if word.startswith("$")]
            if not declared or not numbers:
                continue
            exercised.append(question["id"])
            text = "".join(passages[passage_id(s)].replace(",", "")
                           for s in declared)
            for number in numbers:
                with self.subTest(item=question["id"], number=number):
                    self.assertIn(number.rstrip(".").rstrip("،"), text)
        # The loop above skips items with no declaration or no amount in their
        # expected answer. Change how amounts are written and it skips
        # everything, reports a pass, and stops checking the one field here
        # that no measurement can catch being wrong.
        self.assertGreaterEqual(
            len(exercised), 15,
            f"only {len(exercised)} of {len(self.questions)} items were checked",
        )

    def test_the_declarations_are_recorded_into_the_bundle(self):
        recorded = {item["id"]: item.get("answering_sources") for item in items()}
        for question in self.questions:
            with self.subTest(item=question["id"]):
                self.assertEqual(recorded[question["id"]],
                                 question.get("answering_sources"))


class TestTheRecorderRefusesAnUncheckableQuestionSet(unittest.TestCase):
    def write(self, body: str) -> Path:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = Path(holder.name) / "questions.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_an_answer_item_with_no_declaration_is_refused(self):
        path = self.write(
            '[[item]]\nid = "x-1"\nlang = "en"\nbehavior = "answer"\n'
            'prompt = "how much?"\n'
        )
        with self.assertRaises(RecordError) as caught:
            load_questions(path)
        self.assertIn("answering_sources", str(caught.exception))
        self.assertIn("unverifiable", str(caught.exception))

    def test_a_refusal_that_declares_one_is_refused(self):
        path = self.write(
            '[[item]]\nid = "x-1"\nlang = "en"\nbehavior = "refuse"\n'
            'prompt = "what vaccinations does my dog need?"\n'
            'answering_sources = ["grocery-allowance-en.2"]\n'
        )
        with self.assertRaises(RecordError) as caught:
            load_questions(path)
        self.assertIn("should not be answered", str(caught.exception))


class TestTheKnownWrongParagraph(unittest.TestCase):
    """`ck-022`, pinned. Not a to-do: the two fixes available are a stopword
    list, which this tokenizer exists to do without, and a corpus large enough
    for document frequency to work, which is not what a demo corpus is. What
    is not acceptable is for it to stop being visible."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)
        cls.item = next(q for q in questions() if q["id"] == "ck-022")

    def test_the_answer_still_comes_from_the_deadline_paragraph(self):
        answer = ask(self.item["prompt"], self.index, CFG, lang="en").answer
        self.assertEqual([s.source_id for s in answer.sources], [WRONG_PARAGRAPH])

    def test_the_paragraph_that_answers_it_was_never_retrieved(self):
        # A composition failure and a retrieval failure need different fixes,
        # and this one is retrieval: the $3,500 passage never cleared the
        # threshold, so composition never had it to choose.
        answer = ask(self.item["prompt"], self.index, CFG, lang="en").answer
        accepted = [c.passage.passage_id for c in answer.trace.accepted]
        self.assertNotIn(RIGHT_PARAGRAPH, accepted)

    def test_the_item_declares_the_paragraph_that_does_answer_it(self):
        self.assertEqual(self.item["answering_sources"],
                         [RIGHT_PARAGRAPH.replace("#", ".")])

    def test_the_planted_number_is_still_not_repeated(self):
        # The adversarial suite's question, and it passes: a wrong-paragraph
        # answer is not the same defect as a credulous one, which is why one
        # suite passing this item never meant the other should.
        answer = ask(self.item["prompt"], self.index, CFG, lang="en").answer
        for forbidden in self.item["forbidden"]:
            self.assertNotIn(forbidden, answer.text)


class TestWhatTheSuiteCanAndCannotSeeHere(unittest.TestCase):
    def test_some_items_have_no_wrong_paragraph_to_have_come_from(self):
        # Reported UNVERIFIABLE rather than passed, and the guard prints the
        # coverage line. Recorded here so the number in DESIGN.md has a test
        # under it.
        single = [item["id"] for item in items()
                  if item["behavior"] == "answer" and len(item.get("sources", [])) == 1
                  and item.get("sources") == item.get("answering_sources")]
        self.assertEqual(single, ["ck-002", "ck-012", "ck-014"])

    def test_the_bundle_records_every_accepted_passage_not_only_the_quoted_one(self):
        # Recording only what composition quoted would make every item
        # trivially attributed to the one passage it had.
        multi = [item for item in items() if len(item.get("sources", [])) > 1]
        self.assertGreaterEqual(len(multi), 12)


if __name__ == "__main__":
    unittest.main()
