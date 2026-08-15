"""R2 + R3: grounded answering with citations, and first-class refusal.

The in-corpus/off-topic probe sets double as the threshold calibration
check promised in DESIGN.md: if corpus or scorer changes squeeze the score
gap the default threshold sits in, these tests fail rather than letting the
calibration drift silently.
"""

import unittest
from pathlib import Path

from cairn.answer import compose
from cairn.config import Config
from cairn.index import build_index
from cairn.retrieve import retrieve

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CFG = Config()  # built-in defaults: the exact configuration a clean checkout runs

# (question, passage id that contains the fact, the fact itself)
IN_CORPUS_PROBES = [
    (
        "How much is the monthly grocery allowance for one person?",
        "grocery-allowance-en#2",
        "$212",
    ),
    (
        "How much unpaid rent does the housing relief grant cover?",
        "housing-relief-en#2",
        "$3,500",
    ),
    (
        "When is the deadline to apply for the housing grant?",
        "housing-relief-en#4",
        "September 30",
    ),
    ("How much does the GoPass cost per year?", "transit-pass-en#2", "$20"),
    (
        "Cuanto recibe un hogar de una persona del subsidio de alimentos?",
        "grocery-allowance-es#2",
        "$212",
    ),
    ("Cuanto cubre la subvencion de alivio de vivienda?", "housing-relief-es#2", "$3,500"),
]

OFF_TOPIC_PROBES = [
    "Can you help me renew my drivers license?",
    "What is the capital of France?",
    "How do I file my federal income taxes?",
    "Is the library open on Sunday?",
    "What vaccinations does my dog need?",
    "Do you offer job training classes?",
]


def ask(index, question, threshold=None):
    trace = retrieve(
        question,
        index,
        threshold=CFG.threshold if threshold is None else threshold,
        candidates=CFG.candidates,
    )
    return compose(trace, max_passages=CFG.max_passages, contact=CFG.contact)


class TestGroundedAnswering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_in_corpus_questions_answer_with_fact_and_citation(self):
        for question, fact_passage, fact in IN_CORPUS_PROBES:
            with self.subTest(question=question):
                answer = ask(self.index, question)
                self.assertEqual(answer.kind, "grounded")
                self.assertIn(fact, answer.text, "answer must contain the policy fact")
                self.assertGreaterEqual(len(answer.sources), 1)
                cited_ids = {s.source_id for s in answer.sources}
                self.assertIn(
                    fact_passage,
                    cited_ids,
                    "the passage containing the fact must be among the citations",
                )

    def test_numeric_facts_are_traceable_to_a_cited_passage(self):
        # Extractive composition makes this structural; this test guards the
        # invariant against future composition changes.
        passages_by_id = {p.passage_id: p for p in self.index.passages}
        for question, _, fact in IN_CORPUS_PROBES:
            with self.subTest(question=question):
                answer = ask(self.index, question)
                self.assertTrue(
                    any(fact in passages_by_id[s.source_id].text for s in answer.sources),
                    f"fact {fact!r} must appear in a cited passage",
                )

    def test_sources_carry_titles_and_stable_ids(self):
        answer = ask(self.index, IN_CORPUS_PROBES[0][0])
        for source in answer.sources:
            self.assertTrue(source.title)
            doc_id, _, ordinal = source.source_id.partition("#")
            self.assertTrue(doc_id and ordinal.isdigit())

    def test_same_question_yields_identical_output(self):
        question = IN_CORPUS_PROBES[0][0]
        first, second = ask(self.index, question), ask(self.index, question)
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.sources, second.sources)
        self.assertEqual(first.to_payload(), second.to_payload())


class TestRefusal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_off_topic_questions_refuse_with_no_sources(self):
        for question in OFF_TOPIC_PROBES:
            with self.subTest(question=question):
                answer = ask(self.index, question)
                self.assertEqual(answer.kind, "refusal")
                self.assertEqual(answer.sources, (), "a refusal carries no sources")
                self.assertIn(CFG.contact, answer.text, "refusal points to the human channel")

    def test_refusal_contains_no_corpus_content(self):
        # No partial guess: nothing from any corpus passage leaks into a refusal.
        answer = ask(self.index, "What vaccinations does my dog need?")
        for passage in self.index.passages:
            for line in passage.text.splitlines():
                self.assertNotIn(line, answer.text)

    def test_refusal_is_countable_in_machine_output(self):
        payload = ask(self.index, OFF_TOPIC_PROBES[0]).to_payload()
        self.assertEqual(payload["kind"], "refusal")
        self.assertFalse(payload["grounded"])
        self.assertEqual(payload["sources"], [])

    def test_threshold_is_the_gate_between_the_outcomes(self):
        # Config-driven behavior: the same question flips to refusal when the
        # configured threshold rises above its retrieval scores.
        question = IN_CORPUS_PROBES[0][0]
        self.assertEqual(ask(self.index, question).kind, "grounded")
        self.assertEqual(ask(self.index, question, threshold=0.99).kind, "refusal")

    def test_empty_and_nonsense_queries_refuse(self):
        for question in ("", "   ", "zzzzqqqq wwwwxxxx"):
            with self.subTest(question=repr(question)):
                self.assertEqual(ask(self.index, question).kind, "refusal")


class TestTraceSubstrate(unittest.TestCase):
    """The retrieval trace is M2's explain-mode substrate; pin its semantics now."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def test_trace_marks_accept_reject_and_groundedness(self):
        trace = retrieve(
            IN_CORPUS_PROBES[0][0],
            self.index,
            threshold=CFG.threshold,
            candidates=CFG.candidates,
        )
        self.assertTrue(trace.grounded)
        for c in trace.candidates:
            self.assertEqual(c.accepted, c.score >= trace.threshold)
        scores = [c.score for c in trace.candidates]
        self.assertEqual(scores, sorted(scores, reverse=True), "candidates are ranked")

    def test_ungrounded_trace(self):
        trace = retrieve(
            "What vaccinations does my dog need?",
            self.index,
            threshold=CFG.threshold,
            candidates=CFG.candidates,
        )
        self.assertFalse(trace.grounded)
        self.assertEqual(trace.accepted, ())


if __name__ == "__main__":
    unittest.main()
