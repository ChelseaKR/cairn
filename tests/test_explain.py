"""R5: operator explain mode separates retrieval failure from answer failure."""

import tempfile
import unittest
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.explain import diagnose, excerpt, render, trace_payload
from cairn.index import build_index

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CFG = Config()

GROUNDED_Q = "How much is the monthly grocery allowance for one person?"
MISS_Q = "What vaccinations does my dog need?"
NO_OVERLAP_Q = "zzzzqqqq wwwwxxxx"

# A two-part question. Retrieval finds both halves and accepts both passages;
# composition quotes only the best one, so the answer is missing the half the
# operator asked about second. This is the case explain mode exists to
# disambiguate: retrieval did its job and the answer is still incomplete.
TRUNCATION_Q = "What does the housing grant cover and when do I apply?"
TRUNCATION_FACT = "September 30"
TRUNCATION_PASSAGE = "housing-relief-en#4"


class ExplainHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def ask(self, question, *, threshold=None, max_passages=None):
        cfg = Config(
            threshold=CFG.threshold if threshold is None else threshold,
            max_passages=CFG.max_passages if max_passages is None else max_passages,
        )
        result = ask(question, self.index, cfg)
        return result, diagnose(result.answer, max_passages=cfg.max_passages)


class TestStageSeparation(ExplainHarness):
    def test_retrieval_miss_is_blamed_on_retrieval(self):
        result, diag = self.ask(MISS_Q)
        self.assertEqual(result.answer.kind, "refusal")
        self.assertEqual(diag.blame, "retrieval")
        self.assertFalse(diag.stage("retrieval").ok)
        self.assertEqual(diag.stage("retrieval").code, "below-threshold")
        self.assertEqual(diag.stage("answer").code, "no-evidence")
        self.assertIn("0.165", diag.stage("retrieval").detail, "the threshold is quoted")

    def test_no_lexical_overlap_is_distinguished_from_a_low_score(self):
        _, diag = self.ask(NO_OVERLAP_Q)
        self.assertEqual(diag.stage("retrieval").code, "no-lexical-overlap")
        self.assertEqual(diag.blame, "retrieval")

    def test_grounded_answer_clears_both_stages(self):
        result, diag = self.ask(GROUNDED_Q, max_passages=8)
        self.assertEqual(result.answer.kind, "grounded")
        self.assertIsNone(diag.blame)
        self.assertTrue(diag.stage("retrieval").ok)
        self.assertEqual(diag.stage("answer").code, "composed")
        self.assertEqual(diag.dropped, ())

    def test_a_missing_fact_with_healthy_retrieval_is_blamed_on_composition(self):
        # The whole point of R5: a bad answer, diagnosed to the right stage.
        result, diag = self.ask(TRUNCATION_Q, max_passages=1)
        self.assertEqual(result.answer.kind, "grounded")
        self.assertNotIn(TRUNCATION_FACT, result.answer.text, "the answer is missing the fact")
        self.assertTrue(diag.stage("retrieval").ok, "retrieval is not at fault here")
        self.assertEqual(diag.stage("answer").code, "composed-truncated")
        self.assertIn(TRUNCATION_PASSAGE, [c.passage.passage_id for c in diag.dropped])
        self.assertIn("max_passages", diag.stage("answer").detail)

        # ... and with room to compose, the same question answers correctly.
        result, diag = self.ask(TRUNCATION_Q, max_passages=8)
        self.assertIn(TRUNCATION_FACT, result.answer.text)
        self.assertEqual(diag.stage("answer").code, "composed")


class TestTraceContents(ExplainHarness):
    def test_every_candidate_carries_score_and_threshold_verdict(self):
        result, _ = self.ask(GROUNDED_Q)
        payload = trace_payload(result.answer.trace)
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
        result, _ = self.ask(MISS_Q)
        self.assertEqual(result.answer.kind, "refusal")
        payload = trace_payload(result.answer.trace)
        self.assertTrue(
            payload["candidates"], "a refusal still shows what was considered and rejected"
        )
        self.assertTrue(all(not c["accepted"] for c in payload["candidates"]))

    def test_excerpt_is_single_line_and_bounded(self):
        long_text = "word " * 200
        self.assertLessEqual(len(excerpt(long_text)), 88)
        self.assertNotIn("\n", excerpt("two\n\nlines"))


class TestTermEvidence(ExplainHarness):
    """The trace says which of the question's words each passage held.

    A score alone cannot distinguish "this passage is about something else"
    from "the corpus has never heard of this word", and those need different
    fixes. The term evidence is what makes the difference visible.
    """

    def test_query_terms_partition_into_matched_unmatched_and_ignored(self):
        for question in (GROUNDED_Q, MISS_Q, TRUNCATION_Q, "who can get the discount bus pass"):
            with self.subTest(question=question):
                result, _ = self.ask(question)
                trace = result.answer.trace
                matched = {t for c in trace.candidates for t in c.matched}
                unmatched, ignored = set(trace.unmatched), set(trace.ignored)
                self.assertEqual(matched & unmatched, set())
                self.assertEqual(matched & ignored, set())
                self.assertEqual(unmatched & ignored, set())
                # Nothing is invented and nothing is silently dropped: every
                # term the question tokenized to is accounted for exactly once.
                self.assertTrue(matched <= set(trace.query_terms))
                self.assertTrue(unmatched | ignored <= set(trace.query_terms))
                self.assertEqual(
                    set(trace.scoring_terms), set(trace.query_terms) - ignored
                )

    def test_a_candidate_matched_at_least_one_term_or_it_would_not_have_scored(self):
        result, _ = self.ask(MISS_Q)
        self.assertTrue(result.answer.trace.candidates)
        for candidate in result.answer.trace.candidates:
            self.assertTrue(candidate.matched, candidate.passage.passage_id)
            for term in candidate.matched:
                self.assertIn(term, candidate.passage.term_counts)

    def test_a_word_the_corpus_never_saw_is_reported_as_absent_not_as_common(self):
        result, _ = self.ask(MISS_Q)
        trace = result.answer.trace
        self.assertIn("dog", trace.unmatched)
        self.assertNotIn("dog", trace.ignored)

    def test_a_word_the_corpus_suppressed_is_reported_as_common_not_as_absent(self):
        # "the" is in most English passages, so document frequency zeroes it.
        # Calling that "no passage contained it" would be a lie the operator
        # could act on.
        result, _ = self.ask("who can get the discount bus pass")
        trace = result.answer.trace
        self.assertIn("the", trace.ignored)
        self.assertNotIn("the", trace.unmatched)

    def test_the_report_and_the_json_carry_the_same_term_evidence(self):
        result, diag = self.ask(MISS_Q)
        trace = result.answer.trace
        payload = trace_payload(trace)
        self.assertEqual(payload["query_terms"], list(trace.query_terms))
        self.assertEqual(payload["unmatched_terms"], list(trace.unmatched))
        self.assertEqual(payload["ignored_terms"], list(trace.ignored))
        self.assertEqual(
            [c["matched_terms"] for c in payload["candidates"]],
            [list(c.matched) for c in trace.candidates],
        )
        report = render(result, diag, index_summary="test index")
        self.assertIn("question terms:", report)
        self.assertIn("in no passage:", report)
        for candidate in trace.candidates:
            self.assertIn(f"matched {len(candidate.matched)}/", report)

    def test_the_below_threshold_verdict_names_the_words_the_corpus_lacks(self):
        result, diag = self.ask(MISS_Q)
        detail = diag.stage("retrieval").detail
        self.assertEqual(diag.stage("retrieval").code, "below-threshold")
        for term in result.answer.trace.unmatched:
            self.assertIn(term, detail)
        self.assertIn("coverage gap", detail)


class TestReport(ExplainHarness):
    def test_report_names_the_stage_to_diagnose(self):
        result, diag = self.ask(MISS_Q)
        report = render(result, diag, index_summary="test index")
        self.assertIn("Stage 1 - retrieval: FAILED", report)
        self.assertIn("Stage 2 - answer: NOT REACHED", report)
        self.assertIn("Diagnose at: retrieval.", report)
        self.assertIn("NOT GROUNDED", report)

    def test_report_lists_accepted_and_rejected_candidates(self):
        result, diag = self.ask(GROUNDED_Q)
        report = render(result, diag, index_summary="test index")
        for candidate in result.answer.trace.candidates:
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
        plain = ask(GROUNDED_Q, self.index, CFG).answer
        explained, diagnosis = self.ask(GROUNDED_Q)
        render(explained, diagnosis, index_summary="test index")
        self.assertEqual(plain.text, explained.answer.text)
        self.assertEqual(plain.sources, explained.answer.sources)
        self.assertEqual(plain.to_payload(), explained.answer.to_payload())


class TestLanguageInTheTrace(ExplainHarness):
    """A trace that hid the language filter would misdirect the operator."""

    def test_the_report_states_the_language_decision_and_every_attempt(self):
        result, diagnosis = self.ask("How much does the GoPass cost per year?")
        report = render(result, diagnosis, index_summary="test index")
        self.assertIn("Language:  en", report)
        self.assertIn("Attempt 1 (restricted to 'en')", report)
        self.assertIn("excluded", report, "the report says what the filter removed")

    def test_a_widened_search_appears_as_a_second_attempt(self):
        cfg = Config()
        result = ask("How much does the GoPass cost per year?", self.index, cfg, lang="es")
        report = render(
            result,
            diagnose(result.answer, max_passages=cfg.max_passages),
            index_summary="test index",
        )
        self.assertIn("Attempt 1 (restricted to 'es')", report)
        self.assertIn("Attempt 2 (widened to every language)", report)
        self.assertIn("cross-language fallback", report)

    def test_a_language_the_corpus_does_not_cover_is_named_as_a_coverage_gap(self):
        # An interface language with no corpus behind it is a coverage gap, and
        # the operator should not have to guess that from an empty score list.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "only-english.md").write_text(
                "---\nid: only-en\ntitle: Only English\nlang: en\n---\n"
                "The grocery allowance is $212 per month.\n",
                encoding="utf-8",
            )
            index = build_index(tmp)
            cfg = Config(cross_language_fallback=False)
            result = ask("ما هي حدود الدخل؟", index, cfg, lang="ar")
            diagnosis = diagnose(result.answer, max_passages=cfg.max_passages)
            self.assertEqual(result.answer.kind, "refusal")
            self.assertEqual(diagnosis.stage("retrieval").code, "no-passages-in-language")
            self.assertEqual(diagnosis.blame, "retrieval")
            report = render(result, diagnosis, index_summary="test index")
            self.assertIn("corpus coverage gap", report)


if __name__ == "__main__":
    unittest.main()
