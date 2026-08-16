"""R2 + R3: grounded answering with citations, and first-class refusal.

The probe sets in ``tests/probes.py`` double as the threshold calibration
check promised in DESIGN.md: if a corpus or scorer change squeezes the score
gap the default threshold sits in, these tests fail rather than letting the
calibration drift silently.
"""

import tempfile
import unittest
from pathlib import Path

from cairn.answer import Answer, compose
from cairn.config import Config, ConfigError, load_config
from cairn.engine import ask
from cairn.index import build_index
from cairn.retrieve import retrieve
from tests.probes import (
    IN_CORPUS,
    MEASURED_BEST_OFF_TOPIC,
    MEASURED_WORST_IN_CORPUS,
    OFF_TOPIC,
)

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CFG = Config()  # built-in defaults: the exact configuration a clean checkout runs


class EngineHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def answer(self, question, **kwargs):
        return ask(question, self.index, CFG, **kwargs).answer


class TestGroundedAnswering(EngineHarness):
    def test_in_corpus_questions_answer_with_fact_and_citation(self):
        for question, fact_passage, fact in IN_CORPUS:
            with self.subTest(question=question):
                answer = self.answer(question)
                self.assertEqual(answer.kind, "grounded")
                self.assertIn(fact, answer.text, "answer must contain the policy fact")
                self.assertGreaterEqual(len(answer.sources), 1)
                cited = {s.source_id for s in answer.sources}
                self.assertIn(
                    fact_passage, cited, "the passage containing the fact must be cited"
                )

    def test_numeric_facts_are_traceable_to_a_cited_passage(self):
        # Extractive composition makes this structural; this test guards the
        # invariant against future composition changes.
        passages = {p.passage_id: p for p in self.index.passages}
        for question, _, fact in IN_CORPUS:
            with self.subTest(question=question):
                answer = self.answer(question)
                self.assertTrue(
                    any(fact in passages[s.source_id].text for s in answer.sources),
                    f"fact {fact!r} must appear in a cited passage",
                )

    def test_answer_text_is_exactly_the_cited_passages(self):
        passages = {p.passage_id: p for p in self.index.passages}
        for question, _, _ in IN_CORPUS:
            with self.subTest(question=question):
                answer = self.answer(question)
                quoted = "\n\n".join(passages[s.source_id].text for s in answer.sources)
                self.assertEqual(answer.text, quoted, "no text is composed, only quoted")

    def test_sources_carry_titles_stable_ids_and_a_language(self):
        answer = self.answer(IN_CORPUS[0][0])
        # A refusal has no sources, so a threshold or tokenizer change that
        # turned this question into one would empty the loop and leave the
        # only check on citation shape reporting green.
        self.assertEqual(answer.kind, "grounded")
        self.assertTrue(answer.sources)
        for source in answer.sources:
            self.assertTrue(source.title)
            doc_id, _, ordinal = source.source_id.partition("#")
            self.assertTrue(doc_id and ordinal.isdigit())
            self.assertIn(source.lang, self.index.language_codes)

    def test_same_question_yields_identical_output(self):
        question = IN_CORPUS[0][0]
        first, second = self.answer(question), self.answer(question)
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.sources, second.sources)
        self.assertEqual(first.to_payload(), second.to_payload())


class TestRefusal(EngineHarness):
    def test_off_topic_questions_refuse_with_no_sources(self):
        for question in OFF_TOPIC:
            with self.subTest(question=question):
                answer = self.answer(question)
                self.assertEqual(answer.kind, "refusal")
                self.assertEqual(answer.sources, (), "a refusal carries no sources")
                self.assertIn(
                    "555-0142", answer.text, "refusal points to the human channel"
                )

    def test_refusal_contains_no_corpus_content(self):
        # No partial guess: nothing from any corpus passage leaks into a refusal.
        answer = self.answer("What vaccinations does my dog need?")
        for passage in self.index.passages:
            for line in passage.text.splitlines():
                self.assertNotIn(line, answer.text)

    def test_refusal_is_countable_in_machine_output(self):
        payload = self.answer(OFF_TOPIC[0]).to_payload()
        self.assertEqual(payload["kind"], "refusal")
        self.assertFalse(payload["grounded"])
        self.assertEqual(payload["sources"], [])

    def test_empty_and_nonsense_queries_refuse(self):
        for question in ("", "   ", "zzzzqqqq wwwwxxxx"):
            with self.subTest(question=repr(question)):
                self.assertEqual(self.answer(question).kind, "refusal")


class TestNoConfigurationCanEmitAnUnsourcedAnswer(EngineHarness):
    """The core promise, held against the configuration rather than the corpus.

    "There is no code path that emits an answer without supporting corpus
    passages" was true of every corpus and every question, and false of one
    configuration. `Config(max_passages=0)` — a plausible reading of "no
    limit" — sliced the accepted passages away in composition while the trace
    still said passages had been accepted, so `kind` stayed `"grounded"`,
    `to_payload()["grounded"]` stayed true, and what came back was an empty
    answer with no sources under it. A negative value was quieter: `[:-1]`
    drops the last accepted passage rather than meaning "all of them".

    `cairn.toml` could not reach either, because `load_config` checked the
    bounds. Nothing else did, and this is a reference implementation whose
    whole invitation is that somebody imports it. The bounds live on `Config`
    now, and nothing here had a test.
    """

    UNUSABLE = (
        ("max_passages", 0),
        ("max_passages", -1),
        ("candidates", 0),
        ("threshold", 0.0),
        ("threshold", 1.5),
    )

    def test_a_configuration_that_could_break_the_promise_is_refused(self):
        for key, value in self.UNUSABLE:
            with self.subTest(**{key: value}):
                with self.assertRaises(ConfigError):
                    Config(**{key: value})

    def test_the_file_and_the_constructor_are_held_to_the_same_bounds(self):
        # Two sets of rules is how the caller-side hole opened in the first
        # place: the loader enforced them and the type did not.
        for key, value in self.UNUSABLE:
            with self.subTest(**{key: value}), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "cairn.toml"
                path.write_text(f"[retrieval]\n{key} = {value}\n", encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_every_usable_configuration_grounds_on_at_least_one_source(self):
        for cfg in (
            Config(),
            Config(max_passages=1),
            Config(max_passages=8),
            Config(candidates=1),
            Config(threshold=0.99),
            Config(cross_language_fallback=False),
        ):
            for question in (IN_CORPUS[0][0], OFF_TOPIC[0]):
                with self.subTest(cfg=cfg.max_passages, question=question):
                    answer = ask(question, self.index, cfg).answer
                    payload = answer.to_payload()
                    self.assertEqual(payload["grounded"], answer.kind == "grounded")
                    if answer.kind == "grounded":
                        self.assertTrue(answer.sources, "grounded with nothing under it")
                        self.assertTrue(answer.text.strip())
                    else:
                        self.assertEqual(answer.sources, ())

    def test_a_file_that_mentions_no_contact_is_the_same_as_no_file(self):
        # A key absent from the file means "use the default", and this one did
        # not: an absent `contact_by_language` was passed through as `{}`,
        # which overrode the type's per-language defaults. So a cairn.toml
        # setting only `[corpus] path` ended an Arabic refusal with the
        # English contact line, while *no config file at all* ended it in
        # Arabic. The file was less safe than its absence, for a key it never
        # mentioned.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text("[corpus]\npath = 'corpus/demo'\n", encoding="utf-8")
            self.assertEqual(load_config(path).contact_by_language,
                             Config().contact_by_language)
            for lang in ("en", "es", "ar"):
                self.assertEqual(load_config(path).contact_for(lang),
                                 Config().contact_for(lang))

    def test_an_operator_contact_is_never_padded_out_with_demo_ones(self):
        # The other half. Somebody who states one channel and no table has
        # stated it for every language, and filling Cairn's fictional Spanish
        # and Arabic phone numbers in around it would put an invented contact
        # into a real deployment.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text("[refusal]\ncontact = 'the front desk'\n", encoding="utf-8")
            cfg = load_config(path)
            for lang in ("en", "es", "ar"):
                with self.subTest(lang=lang):
                    self.assertEqual(cfg.contact_for(lang), "the front desk")

    def test_compose_refuses_the_bound_the_config_refuses(self):
        # `Config` grew these bounds; `compose` is a public function taking
        # the number directly and did not. `accepted[:0]` returns a grounded
        # answer with no sources and `accepted[:-1]` silently drops the last
        # accepted passage, so the promise the config docstring makes was one
        # import away from being false again.
        trace = retrieve(
            IN_CORPUS[0][0], self.index, threshold=CFG.threshold,
            candidates=CFG.candidates, lang="en",
        )
        self.assertTrue(trace.accepted, "this fixture needs an accepted passage")
        for value in (0, -1):
            with self.subTest(max_passages=value), self.assertRaises(ValueError):
                compose(trace, max_passages=value, refusal_text="no", lang="en")

    def test_the_two_outcomes_are_enforced_by_the_type(self):
        # Not by whichever branch of `compose` a caller happened to reach.
        # `Answer` is public, frozen, and serializes `"grounded": true` off
        # `kind` alone, so a hand-built one was the same defect as the
        # max_passages bug with the bug's own layer removed.
        trace = retrieve(
            IN_CORPUS[0][0], self.index, threshold=CFG.threshold,
            candidates=CFG.candidates, lang="en",
        )
        real = compose(trace, max_passages=1, refusal_text="no", lang="en")
        with self.assertRaises(ValueError):
            Answer(kind="grounded", text="something", sources=(), trace=trace, lang="en")
        with self.assertRaises(ValueError):
            Answer(kind="grounded", text="   ", sources=real.sources, trace=trace, lang="en")
        with self.assertRaises(ValueError):
            Answer(kind="refusal", text="no", sources=real.sources, trace=trace, lang="en")
        with self.assertRaises(ValueError):
            Answer(kind="refusal", text="no", sources=(), trace=trace, lang="en",
                   notice="the source is in another language")
        with self.assertRaises(ValueError):
            Answer(kind="partial", text="x", sources=(), trace=trace, lang="en")


class TestThresholdCalibration(EngineHarness):
    """The default threshold is a measurement, and this is the measurement."""

    def scores(self, questions):
        tops = []
        for question in questions:
            result = ask(question, self.index, CFG)
            trace = result.answer.trace
            tops.append(trace.candidates[0].score if trace.candidates else 0.0)
        return tops

    def test_threshold_sits_inside_the_measured_gap(self):
        worst_in = min(self.scores(q for q, _, _ in IN_CORPUS))
        best_off = max(self.scores(OFF_TOPIC))
        self.assertGreaterEqual(worst_in, MEASURED_WORST_IN_CORPUS - 0.001)
        self.assertLessEqual(best_off, MEASURED_BEST_OFF_TOPIC + 0.001)
        self.assertLess(best_off, CFG.threshold, "an off-topic question would be answered")
        self.assertGreater(worst_in, CFG.threshold, "a real question would be refused")

    def test_the_gap_keeps_a_working_margin_on_both_sides(self):
        worst_in = min(self.scores(q for q, _, _ in IN_CORPUS))
        best_off = max(self.scores(OFF_TOPIC))
        self.assertGreater(
            CFG.threshold - best_off, 0.01, "no headroom above the off-topic band"
        )
        self.assertGreater(
            worst_in - CFG.threshold, 0.01, "no headroom below the in-corpus band"
        )

    def test_threshold_is_the_gate_between_the_outcomes(self):
        # Config-driven behavior: the same question flips to refusal when the
        # configured threshold rises above its retrieval scores.
        strict = Config(threshold=0.99)
        question = IN_CORPUS[0][0]
        self.assertEqual(self.answer(question).kind, "grounded")
        self.assertEqual(ask(question, self.index, strict).answer.kind, "refusal")


class TestTheKnownColloquialRefusal(EngineHarness):
    """Why `ck-015` stays refused, pinned as evidence rather than as a verdict.

    "who can get the discount bus pass" is the one question in the audit's
    evidence that Cairn refuses and should not. Two earlier readings of that
    were both wrong, and each had an obvious fix that made the system worse:

    - *The threshold is too high.* It is not. Lowering the gate answers the
      question from the fare paragraph — a confident, well-cited, wrong
      answer, which is worse than a refusal and harder to notice.
    - *The ranking is wrong.* This was the previous diagnosis, and measuring
      it is what disproved it. Three passage-level ranking signals were built
      and measured over twenty-one configurations (DESIGN.md, "The
      colloquial-recall failure"); the eligibility passage never reached the
      top four in any of them, and every configuration that answered `ck-015`
      answered it from the wrong paragraph while letting off-topic questions
      through.

    The real reason is below, and it is a property of the corpus, not of the
    scorer: the eligibility passage's *entire* overlap with this question is
    the word "who", the weakest content term the question has, and two
    passages in other documents hold that same word plus another. Retrieval is
    reporting the evidence correctly. There is no reweighting of what these
    passages contain that puts the right one first.

    So these tests pin the evidence. If a corpus edit or a tokenizer change
    ever makes the eligibility passage a lexical answer to this question, they
    fail and name the assumption that moved — which is the correct moment for
    them to fail, and a more informative failure than "it stopped refusing".
    """

    QUESTION = "who can get the discount bus pass"
    ELIGIBILITY = "transit-pass-en#3"
    FARE = "transit-pass-en#2"
    # Measured 2026-08-15. The eligibility passage shares exactly this much
    # with the question; the two passages that dominate it are in *other*
    # documents and share the same term plus "can".
    ELIGIBILITY_OVERLAP = ("who",)
    DOMINATING = ("grocery-allowance-en#3", "housing-relief-en#3")

    def trace(self):
        return retrieve(
            self.QUESTION, self.index, threshold=CFG.threshold, candidates=CFG.candidates
        )

    def test_the_eligibility_passage_is_not_what_this_question_retrieves(self):
        trace = self.trace()
        self.assertTrue(trace.candidates, "the question should at least score something")
        self.assertEqual(
            trace.candidates[0].passage.passage_id,
            self.FARE,
            "retrieval now ranks this differently — re-read the evidence below",
        )

    def test_the_eligibility_passage_shares_one_weak_word_with_the_question(self):
        # The finding the ranking experiments produced, as a measurement: this
        # is why no reweighting fixes it. The passage does not contain
        # "discount", does not contain "bus" (the corpus says "buses"), does
        # not contain "get", and "GoPass" does not stem to "pass".
        trace = self.trace()
        found = {c.passage.passage_id: c.matched for c in trace.candidates}
        self.assertIn(self.ELIGIBILITY, found, "it should still be a scored candidate")
        self.assertEqual(found[self.ELIGIBILITY], self.ELIGIBILITY_OVERLAP)
        self.assertEqual(found[self.FARE], ("disco", "pass"))
        self.assertIn("bus", trace.unmatched, "no passage in the corpus contains 'bus'")

    def test_two_passages_in_other_documents_hold_strictly_more_of_the_same(self):
        # Strictly more: the same "who", plus "can". A scorer cannot prefer
        # the eligibility passage over these on the evidence they contain,
        # which is the whole reason the refusal is correct rather than lazy.
        trace = self.trace()
        found = {c.passage.passage_id: set(c.matched) for c in trace.candidates}
        weak = found[self.ELIGIBILITY]
        for passage_id in self.DOMINATING:
            with self.subTest(passage=passage_id):
                self.assertTrue(weak < found[passage_id], found.get(passage_id))
                self.assertNotEqual(
                    passage_id.split("#")[0],
                    self.ELIGIBILITY.split("#")[0],
                    "the dominating passages are in other documents entirely",
                )

    def test_so_it_refuses_rather_than_answering_from_the_wrong_paragraph(self):
        self.assertEqual(self.answer(self.QUESTION).kind, "refusal")

    def test_and_the_same_question_asked_formally_is_answered(self):
        # The limit is the phrasing, not the fact: the corpus has it, and
        # naming the program finds the program. (Which paragraph of it comes
        # back is the ranking question above; the document is right.)
        answer = self.answer("Who is eligible for the Harbor GoPass Reduced Fare Program?")
        self.assertEqual(answer.kind, "grounded")
        self.assertTrue(
            all(s.source_id.startswith("transit-pass-en#") for s in answer.sources),
            [s.source_id for s in answer.sources],
        )


class TestTraceSubstrate(EngineHarness):
    """The retrieval trace is what explain mode renders; pin its semantics."""

    def test_trace_marks_accept_reject_and_groundedness(self):
        trace = retrieve(
            IN_CORPUS[0][0], self.index, threshold=CFG.threshold, candidates=CFG.candidates
        )
        self.assertTrue(trace.grounded)
        for candidate in trace.candidates:
            self.assertEqual(candidate.accepted, candidate.score >= trace.threshold)
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


class TestTheCitedTextForm(EngineHarness):
    """One definition of "the answer, with its citations in it".

    It used to live inside the recorder, which meant the audit graded a string
    no client of the served interface could obtain. Now the answer owns it and
    both produce it; `tests/test_live.py` checks the server against the
    recording over a real socket.
    """

    def test_every_source_gets_one_marker_and_the_words_are_untouched(self):
        answer = self.answer(IN_CORPUS[0][0])
        head, _, marks = answer.cited_text.rpartition("\n")
        self.assertEqual(head, answer.text, "markers are appended, nothing is rewritten")
        self.assertEqual(
            marks.split(), [f"[{s.source_id.replace('#', '.')}]" for s in answer.sources]
        )

    def test_a_marker_is_never_a_passage_id_verbatim(self):
        # The inline grammar has no "#" in it, so a marker carrying one would
        # not be read as a citation at all — it would read as an answer that
        # cited nothing.
        answer = self.answer(IN_CORPUS[0][0])
        marks = answer.cited_text.rsplit("\n", 1)[1]
        self.assertNotIn("#", marks)
        self.assertIn("#", answer.sources[0].source_id)

    def test_a_refusal_is_returned_unchanged(self):
        answer = self.answer(OFF_TOPIC[0])
        self.assertEqual(answer.cited_text, answer.text)
        self.assertEqual(answer.to_payload()["cited_text"], answer.text)

    def test_the_served_payload_carries_it(self):
        payload = self.answer(IN_CORPUS[0][0]).to_payload()
        self.assertEqual(payload["cited_text"], self.answer(IN_CORPUS[0][0]).cited_text)
        self.assertTrue(payload["cited_text"].startswith(payload["text"]))


if __name__ == "__main__":
    unittest.main()
