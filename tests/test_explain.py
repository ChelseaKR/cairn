"""R5: operator explain mode separates retrieval failure from answer failure."""

import unittest
from pathlib import Path

from cairn.answer import compose
from cairn.config import Config
from cairn.explain import diagnose, excerpt, render, trace_payload
from cairn.index import build_index
from cairn.retrieve import retrieve

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CFG = Config()

GROUNDED_Q = "How much is the monthly grocery allowance for one person?"
MISS_Q = "What vaccinations does my dog need?"
NO_OVERLAP_Q = "zzzzqqqq wwwwxxxx"

# Retrieval ranks the passage holding the deadline second, so max_passages=1
# composes an answer that is missing the fact the operator asked for. This is
# the case explain mode exists to disambiguate: retrieval did its job.
TRUNCATION_Q = "When is the deadline to apply for the housing grant?"
TRUNCATION_FACT = "September 30"
TRUNCATION_PASSAGE = "housing-relief-en#4"


class ExplainHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def ask(self, question, *, threshold=None, max_passages=None):
        trace = retrieve(
            question,
            self.index,
            threshold=CFG.threshold if threshold is None else threshold,
            candidates=CFG.candidates,
        )
        max_passages = CFG.max_passages if max_passages is None else max_passages
        answer = compose(trace, max_passages=max_passages, contact=CFG.contact)
        return answer, diagnose(answer, max_passages=max_passages)


class TestStageSeparation(ExplainHarness):
    def test_retrieval_miss_is_blamed_on_retrieval(self):
        answer, diag = self.ask(MISS_Q)
        self.assertEqual(answer.kind, "refusal")
        self.assertEqual(diag.blame, "retrieval")
        self.assertFalse(diag.stage("retrieval").ok)
        self.assertEqual(diag.stage("retrieval").code, "below-threshold")
        self.assertEqual(diag.stage("answer").code, "no-evidence")
        self.assertIn("0.200", diag.stage("retrieval").detail, "the threshold is quoted")

    def test_no_lexical_overlap_is_distinguished_from_a_low_score(self):
        _, diag = self.ask(NO_OVERLAP_Q)
        self.assertEqual(diag.stage("retrieval").code, "no-lexical-overlap")
        self.assertEqual(diag.blame, "retrieval")

    def test_grounded_answer_clears_both_stages(self):
        answer, diag = self.ask(GROUNDED_Q, max_passages=8)
        self.assertEqual(answer.kind, "grounded")
        self.assertIsNone(diag.blame)
        self.assertTrue(diag.stage("retrieval").ok)
        self.assertEqual(diag.stage("answer").code, "composed")
        self.assertEqual(diag.dropped, ())

    def test_a_missing_fact_with_healthy_retrieval_is_blamed_on_composition(self):
        # The whole point of R5: a bad answer, diagnosed to the right stage.
        answer, diag = self.ask(TRUNCATION_Q, max_passages=1)
        self.assertEqual(answer.kind, "grounded")
        self.assertNotIn(TRUNCATION_FACT, answer.text, "the answer is missing the fact")
        self.assertTrue(diag.stage("retrieval").ok, "retrieval is not at fault here")
        self.assertEqual(diag.stage("answer").code, "composed-truncated")
        self.assertIn(TRUNCATION_PASSAGE, [c.passage.passage_id for c in diag.dropped])
        self.assertIn("max_passages", diag.stage("answer").detail)

        # ... and with room to compose, the same question answers correctly.
        answer, diag = self.ask(TRUNCATION_Q, max_passages=3)
        self.assertIn(TRUNCATION_FACT, answer.text)
        self.assertEqual(diag.stage("answer").code, "composed")


class TestTraceContents(ExplainHarness):
    def test_every_candidate_carries_score_and_threshold_verdict(self):
        answer, _ = self.ask(GROUNDED_Q)
        payload = trace_payload(answer.trace)
        self.assertEqual(payload["threshold"], CFG.threshold)
        self.assertTrue(payload["candidates"])
        ranks = [c["rank"] for c in payload["candidates"]]
        self.assertEqual(ranks, sorted(ranks))
        for entry in payload["candidates"]:
            self.assertEqual(entry["accepted"], entry["score"] >= CFG.threshold)
            self.assertTrue(entry["excerpt"] and entry["title"] and entry["lang"])
        accepted = [c for c in payload["candidates"] if c["accepted"]]
        rejected = [c for c in payload["candidates"] if not c["accepted"]]
        self.assertTrue(accepted and rejected, "this probe shows both sides of the gate")

    def test_rejected_candidates_are_reported_not_hidden(self):
        answer, _ = self.ask(MISS_Q)
        self.assertEqual(answer.kind, "refusal")
        payload = trace_payload(answer.trace)
        self.assertTrue(
            payload["candidates"], "a refusal still shows what was considered and rejected"
        )
        self.assertTrue(all(not c["accepted"] for c in payload["candidates"]))

    def test_excerpt_is_single_line_and_bounded(self):
        long_text = "word " * 200
        self.assertLessEqual(len(excerpt(long_text)), 88)
        self.assertNotIn("\n", excerpt("two\n\nlines"))


class TestReport(ExplainHarness):
    def test_report_names_the_stage_to_diagnose(self):
        answer, diag = self.ask(MISS_Q)
        report = render(answer, diag, index_summary="test index")
        self.assertIn("Stage 1 - retrieval: FAILED", report)
        self.assertIn("Stage 2 - answer: NOT REACHED", report)
        self.assertIn("Diagnose at: retrieval.", report)
        self.assertIn("NOT GROUNDED", report)

    def test_report_lists_accepted_and_rejected_candidates(self):
        answer, diag = self.ask(GROUNDED_Q)
        report = render(answer, diag, index_summary="test index")
        for candidate in answer.trace.candidates:
            self.assertIn(candidate.passage.passage_id, report)
        self.assertIn("ACCEPT", report)
        self.assertIn("reject", report)
        self.assertIn("GROUNDED", report)

    def test_report_is_deterministic(self):
        first = render(*self.ask(GROUNDED_Q), index_summary="test index")
        second = render(*self.ask(GROUNDED_Q), index_summary="test index")
        self.assertEqual(first, second)


class TestExplainIsObservational(ExplainHarness):
    def test_diagnosing_does_not_change_the_answer(self):
        trace = retrieve(
            GROUNDED_Q, self.index, threshold=CFG.threshold, candidates=CFG.candidates
        )
        plain = compose(trace, max_passages=CFG.max_passages, contact=CFG.contact)
        explained, _ = self.ask(GROUNDED_Q)
        self.assertEqual(plain.text, explained.text)
        self.assertEqual(plain.sources, explained.sources)
        self.assertEqual(plain.to_payload(), explained.to_payload())


if __name__ == "__main__":
    unittest.main()
