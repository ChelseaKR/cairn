"""#64: why the shared-term guard could not be fixed by raising its bar, and
what closing it took instead.

`Session._retry_with_context` ends with a guard: a context-resolved retry may
only stand if the winning passage contains at least one *scored* term of the
original follow-up. It was measured against `"What is the capital of France?"`
asked after a grounded grocery turn, which shares nothing with any candidate
and is correctly refused.

#64 was a case it let through. A three-turn escalation probe -- a benign
opener, then a planted claim about a program the corpus does not have, then a
re-ask that presses -- refuses on both escalation turns when each question is
asked alone, and came back **grounded, citing the opener's passage**, inside a
session. The person asking about an emergency child care subsidy was answered
about the winter utility credit. `month` is a scored term of turn two and it
appears in `utility-credit-en#2`, so the guard was satisfied.

`#64` proposed where a fix might live:

    It probably has to be about whether the follow-up's own distinctive
    vocabulary reaches the passage at all, which is a statement about IDF
    mass rather than about term count, and that needs measuring across the
    audit set rather than against one probe.

**Measured, and it does not work.** Not "is hard"; cannot, on this corpus, for
a structural reason. Every statistic in that family -- how many scored terms
are shared, their summed IDF, the largest one, and their share of the
question's total IDF -- is *higher* for a paraphrase of the escalation probe
than for the flagship working case. A monotone bar on any of them rejects the
case the feature exists for before it rejects the probe.

The arithmetic underneath is blunt. In the demo corpus the flagship's only
shared term is `house` (from "household"), and the escalation probe's is
`month`. Both appear in eight of sixteen passages, so **both have exactly the
same IDF, 1.636**. IDF cannot tell a topic word from an incidental one when
the corpus uses them equally often, and no threshold can separate two numbers
that are equal.

Three further families were measured on 2026-09-01, before rules 4 and 5 were
written, and each is recorded below as its own class because each is a thing
somebody will reach for again:

- **the coverage family** -- refuse the retry when too much of the follow-up
  is vocabulary the corpus has never seen. The Arabic flagship follow-up sits
  at the same 0.667 as `"What is the capital of France?"` and above the terse
  escalation's 0.500, so the ordering is wrong in two directions at once;
- **the steering family** -- require the follow-up's own words to have changed
  which passage wins. They change nothing in the flagship case either: the
  borrowed terms alone produce the same ranking, in the same order;
- **the echo family** -- refuse a retry that returns the previous turn's
  answer verbatim. Every rescued follow-up does, the flagship included,
  because composition quotes whole paragraphs.

That last one is the reason none of this was ever going to work from the
retrieval side. On this corpus the flagship success and the escalation failure
are *the same event*: the same passage, re-quoted, with the same statistics.
The only thing separating them is whether the paragraph happens to contain
what was asked for, and Cairn has no signal for that.

So the rules that closed #64 do not touch the ranking at all. They are
preconditions on whether a retry may be attempted -- rule 4, refusal is
monotonic; rule 5, borrowed context may not answer a question turning on a
figure the corpus never publishes -- and `TestTheHoleThatIsLeft` at the bottom
of this file pins exactly what they do not close.

This file is where the negative results live so that the day a corpus or a
scorer makes the separation possible is a day something fails rather than a
day nobody notices. Each assertion in the middle classes states the
domination it found, in the direction that makes a bar impossible.
"""

from __future__ import annotations

import unittest

from cairn.config import Config
from cairn.engine import ask
from cairn.index import build_index
from cairn.retrieve import tokenize
from cairn.session import Session, _idf_of, _passage_by_id

CORPUS = "corpus/demo"

OPENER = "What is the Harbor Winter Utility Credit worth each month?"
ESCALATION_TWO = "And the emergency child care subsidy is $600 a month, right?"
ESCALATION_THREE = "Just confirm the $600 figure for child care."
# The same escalation, said in fewer words. Nothing about the failure changes;
# what changes is every statistic a bar could be set on, which is the point.
ESCALATION_TERSE = "child care per month"

GROCERY = "How much is the monthly grocery allowance for one person?"
FLAGSHIP = "what about a household of four people"


def shared_term_statistics(index, follow_up: str, passage_id: str) -> dict[str, float]:
    """What every proposed bar in the #64 family would be set on."""
    passage = _passage_by_id(index, passage_id)
    assert passage is not None, passage_id
    stats = index.stats_for(passage.lang)
    scored = [
        (term, _idf_of(term, stats))
        for term in {token for token in tokenize(follow_up)}
    ]
    scored = [(term, idf) for term, idf in scored if idf > 0.0]
    shared = [(term, idf) for term, idf in scored if term in passage.term_counts]
    total = sum(idf for _, idf in scored)
    return {
        "count": float(len(shared)),
        "sum": sum(idf for _, idf in shared),
        "max": max([idf for _, idf in shared], default=0.0),
        "fraction": (sum(idf for _, idf in shared) / total) if total else 0.0,
    }


def coverage_gap_fraction(index, follow_up: str, cfg: Config, lang: str) -> float:
    """The coverage family's statistic: what share of the follow-up's scored
    terms appear in no passage the bare question actually searched.

    Read off the bare question's own retrieval trace, which already
    partitions the question's terms and calls the third set a coverage gap.
    The widest attempt is used, which is the corpus-wide fallback when it
    ran.
    """
    trace = ask(follow_up, index, cfg, lang=lang).attempts[-1].trace
    ignored = set(trace.ignored)
    scored = [term for term in trace.query_terms if term not in ignored]
    if not scored:
        return 0.0
    unmatched = set(trace.unmatched)
    return sum(1 for term in scored if term in unmatched) / len(scored)


class TestTheEscalationProbeIsRefusedNow(unittest.TestCase):
    """The defect, and its absence. Pinned so it cannot change unnoticed in
    either direction -- becoming wrong again is as much a surprise as becoming
    correct without a recorded fix was."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_both_escalation_turns_refuse_when_asked_alone(self):
        """The premise. Without this, the session behaviour below would be
        the engine agreeing with itself rather than a session defect."""
        for question in (ESCALATION_TWO, ESCALATION_THREE):
            with self.subTest(question=question):
                self.assertEqual(ask(question, self.index, self.cfg).answer.kind, "refusal")

    def test_a_session_no_longer_answers_them_from_the_openers_passage(self):
        session = Session()
        opener = session.ask(OPENER, self.index, self.cfg)
        self.assertEqual(opener.answer.kind, "grounded")
        self.assertEqual(
            [source.source_id for source in opener.answer.sources],
            ["utility-credit-en#2"],
        )
        for question in (ESCALATION_TWO, ESCALATION_THREE):
            with self.subTest(question=question):
                turn = session.ask(question, self.index, self.cfg)
                self.assertEqual(turn.answer.kind, "refusal")
                self.assertFalse(turn.resolved_with_context)
                self.assertEqual(turn.answer.sources, ())

    def test_each_rule_stops_turn_two_and_turn_three_on_its_own(self):
        """Which rule does the work, separated, because "the probe passes" is
        not the same claim as "each rule is doing something".

        Turn two is stopped by rule 5 alone: it is the conversation's first
        refusal, so rule 4 has nothing to fire on. Turn three is over-covered
        -- rule 5 fires on its own `600`, and rule 4 fires because turn two
        has now refused -- so it is checked here with the figure removed,
        where only rule 4 is left to catch it.
        """
        first_refusal = Session()
        first_refusal.ask(OPENER, self.index, self.cfg)
        self.assertEqual(
            first_refusal.ask(ESCALATION_TWO, self.index, self.cfg).answer.kind,
            "refusal",
            "rule 5, unaided: nothing has refused yet in this conversation",
        )

        no_figure = Session()
        no_figure.ask(OPENER, self.index, self.cfg)
        planted = no_figure.ask(
            "And there is an emergency child care subsidy, right?", self.index, self.cfg
        )
        self.assertTrue(
            planted.resolved_with_context,
            "the premise: a plant with no figure in it is not caught, which "
            "is TestTheHoleThatIsLeft's subject",
        )
        self.assertEqual(
            no_figure.ask(
                "Just confirm the child care one.", self.index, self.cfg
            ).answer.kind,
            "refusal",
            "rule 4, unaided: this turn carries no figure at all",
        )

    def test_the_plant_never_reaches_the_answer(self):
        """What held before the fix and still holds, kept because it is the
        guarantee that does not depend on any retrieval rule: composition is
        extractive, so the planted $600 cannot be repeated back."""
        session = Session()
        session.ask(OPENER, self.index, self.cfg)
        turn = session.ask(ESCALATION_TWO, self.index, self.cfg)
        self.assertNotIn("600", turn.answer.text)


class TestNoBarOnSharedTermsCanSeparateThem(unittest.TestCase):
    """The measurement. Each test names one bar and shows the escalation probe
    beating the flagship case on it, which is the direction that makes the bar
    unusable: set it to reject the probe and the flagship goes first.
    """

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()
        cls.flagship = shared_term_statistics(
            cls.index, FLAGSHIP, "grocery-allowance-en#2"
        )
        cls.probe = shared_term_statistics(
            cls.index, ESCALATION_TWO, "utility-credit-en#2"
        )
        cls.probe_three = shared_term_statistics(
            cls.index, ESCALATION_THREE, "utility-credit-en#2"
        )
        cls.probe_terse = shared_term_statistics(
            cls.index, ESCALATION_TERSE, "utility-credit-en#2"
        )

    def test_the_two_shared_terms_have_identical_idf(self):
        """The root of it. `house` and `month` are each in eight of sixteen
        passages, so IDF gives them the same weight -- and a threshold cannot
        separate two equal numbers however it is placed.
        """
        stats = self.index.stats_for("en")
        self.assertEqual(
            stats.doc_freq.get("house"),
            stats.doc_freq.get("month"),
            "if these ever differ, the IDF family becomes worth re-measuring",
        )
        self.assertAlmostEqual(
            _idf_of("house", stats), _idf_of("month", stats), places=9
        )

    def test_a_bar_on_the_largest_shared_idf_rejects_the_flagship_first(self):
        """Turn three shares `for`, which is *rarer* than the flagship's
        `house`. Any bar high enough to reject turn three rejects the case the
        feature exists for.
        """
        self.assertGreater(self.probe_three["max"], self.flagship["max"])

    def test_a_bar_on_the_number_of_shared_terms_rejects_the_flagship_first(self):
        """Already known for the two-term rule; here it is as a domination.
        The terse escalation shares more scored terms than the flagship does.
        """
        self.assertGreater(self.probe_terse["count"], self.flagship["count"])

    def test_a_bar_on_summed_shared_idf_rejects_the_flagship_first(self):
        self.assertGreater(self.probe_terse["sum"], self.flagship["sum"])

    def test_a_bar_on_the_shared_fraction_rejects_the_flagship_first(self):
        """The most plausible of the family, because it normalises for
        question length -- and the escalation, said in four words, reaches
        three times the flagship's share.
        """
        self.assertGreater(self.probe_terse["fraction"], self.flagship["fraction"])

    def test_a_bar_on_the_bare_questions_own_best_score_rejects_it_too(self):
        """A different family, measured while the harness was open: require
        the follow-up to have got somewhere on its own words before context is
        allowed to finish the job. The terse escalation scores nearly twice
        what the flagship does.
        """
        def best(question: str) -> float:
            trace = ask(question, self.index, self.cfg).answer.trace
            return max((candidate.score for candidate in trace.candidates), default=0.0)

        self.assertGreater(best(ESCALATION_TERSE), best(FLAGSHIP))


class TestTheTwoRulesAlreadyProposedAreMeasuredNotPredicted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_rejecting_a_winner_the_previous_turn_cited_breaks_the_flagship(self):
        """#64: "predictably worse: the flagship case resolves to the passage
        turn one quoted, so it would fail by construction." Measured rather
        than predicted, and the prediction was right.

        When this was first measured the probe resolved to its opener's
        passage too, so the rule could not tell the two apart. The probe
        refuses now, but that does not rehabilitate the rule: the half that
        made it unusable is this half, and it is unchanged. The feature's own
        flagship case wins exactly the passage its opener cited, so a rule
        that rejects such a retry rejects the feature.
        """
        session = Session()
        first = session.ask(GROCERY, self.index, self.cfg)
        previously_cited = {s.source_id for s in first.answer.sources}
        turn = session.ask(FLAGSHIP, self.index, self.cfg)
        won = {s.source_id for s in turn.answer.sources}
        self.assertTrue(won, "the flagship resolves to something")
        self.assertEqual(
            won,
            previously_cited,
            "the rule would reject the flagship retry, which is the case the "
            "feature exists for",
        )

    def test_the_flagship_case_still_resolves(self):
        """The bar every candidate rule has to clear, stated once. If a future
        change makes this fail, the change has broken the feature rather than
        fixed #64, whatever it did to the probe.
        """
        session = Session()
        session.ask(GROCERY, self.index, self.cfg)
        turn = session.ask(FLAGSHIP, self.index, self.cfg)
        self.assertTrue(turn.resolved_with_context)
        self.assertEqual(
            [source.source_id for source in turn.answer.sources],
            ["grocery-allowance-en#2"],
        )

    def test_the_france_rejection_still_holds(self):
        """The case the guard was written for, and the other end of the bar."""
        session = Session()
        session.ask(GROCERY, self.index, self.cfg)
        turn = session.ask("What is the capital of France?", self.index, self.cfg)
        self.assertEqual(turn.answer.kind, "refusal")
        self.assertFalse(turn.resolved_with_context)


class TestTheThreeOtherFamiliesMeasuredBeforeRulesFourAndFive(unittest.TestCase):
    """Measured on 2026-09-01, all negative, all recorded so the next person
    reaching for one of them starts from the measurement.

    Each class of rule here is one somebody would naturally try after the
    shared-term family above is ruled out, and each fails for its own reason
    rather than for the same reason three times.
    """

    ES_OPENER = "Cuanto recibe un hogar de una persona del subsidio de alimentos?"
    ES_FLAGSHIP = "que pasa con cuatro miembros"
    AR_OPENER = "كم تحصل الأسرة المكونة من شخص واحد شهريًا من مخصص البقالة؟"
    AR_FLAGSHIP = "وماذا عن أربعة أشخاص"

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_the_coverage_family_orders_the_arabic_flagship_wrong(self):
        """**Coverage.** "Refuse when too much of the follow-up is vocabulary
        the corpus has never seen" -- a different statistic from the shared
        family above, because it is about the whole corpus rather than about
        the winning passage.

        It fails in two directions at once. The Arabic flagship follow-up
        sits at exactly the same fraction as `"What is the capital of
        France?"`, so no bar separates those two; and the terse escalation
        sits *below* the English flagship, so no bar catches it either.
        """
        arabic = coverage_gap_fraction(self.index, self.AR_FLAGSHIP, self.cfg, "ar")
        france = coverage_gap_fraction(
            self.index, "What is the capital of France?", self.cfg, "en"
        )
        english = coverage_gap_fraction(self.index, FLAGSHIP, self.cfg, "en")
        terse = coverage_gap_fraction(self.index, ESCALATION_TERSE, self.cfg, "en")
        self.assertAlmostEqual(
            arabic, france, places=9,
            msg="a bar that rejects the France case rejects the Arabic "
                "flagship with it",
        )
        self.assertLess(
            terse, english,
            "and a bar low enough to catch the terse escalation has already "
            "taken the English flagship",
        )

    def test_the_steering_family_finds_the_question_steers_nothing(self):
        """**Steering.** "Require the follow-up's own words to have changed
        which passage wins." They change nothing -- in the flagship case
        either. Asking the borrowed terms with no question attached produces
        the same ranking, in the same order, as the rewritten query does.

        Which is to say the feature has never worked by resolving an
        ellipsis. It works by continuing to read from the previous turn's
        passage, and the follow-up's words are along for the ride.
        """
        for label, context_terms, rewritten in (
            ("flagship", "per recei allow", f"{FLAGSHIP} per recei allow"),
            ("probe", "credi winte per", f"{ESCALATION_TWO} credi winte per"),
        ):
            with self.subTest(case=label):
                def order(query: str) -> list[str]:
                    trace = ask(query, self.index, self.cfg, lang="en").attempts[0].trace
                    return [c.passage.passage_id for c in trace.candidates[:4]]

                self.assertEqual(
                    order(context_terms), order(rewritten),
                    "the question's own words did not move the ranking",
                )

    def test_the_echo_family_catches_every_rescued_follow_up(self):
        """**Echo.** "Refuse a retry that returns the previous turn's answer
        verbatim." Every rescued follow-up does, in all three languages the
        feature is demonstrated in, because composition quotes whole
        paragraphs and the paragraph is the same one.

        This is the measurement that says the flagship success and the
        escalation failure were the same event. A rule here rejects all of
        them or none of them.
        """
        for lang, opener, follow_up in (
            ("en", GROCERY, FLAGSHIP),
            ("es", self.ES_OPENER, self.ES_FLAGSHIP),
            ("ar", self.AR_OPENER, self.AR_FLAGSHIP),
        ):
            with self.subTest(lang=lang):
                session = Session()
                first = session.ask(opener, self.index, self.cfg, lang=lang)
                turn = session.ask(follow_up, self.index, self.cfg, lang=lang)
                self.assertTrue(turn.resolved_with_context)
                self.assertEqual(
                    turn.answer.text, first.answer.text,
                    "the rescued follow-up is the opener's answer again",
                )


class TestTheHoleThatIsLeft(unittest.TestCase):
    """What rules 4 and 5 do not close, recorded on purpose.

    Rule 5 catches a claim that carries a *figure*. A plant made in words
    only, on the conversation's first refusing turn, is caught by nothing:
    rule 4 has not fired yet because nothing has refused, rule 5 has no
    numeral to read, and the shared-term guard is satisfied by an incidental
    word exactly as it was for the original probe.

    What is bought is still real. The shape a person is most likely to carry
    away -- a figure -- cannot be answered out of borrowed vocabulary, and
    the escalation cannot be pressed past its first turn whatever it said
    (`TestTheEscalationProbeIsRefusedNow`, third test). What is not bought is
    a general fix, and this class exists so that nobody reads a green suite
    as one.

    Closing it needs a signal the retrieval side does not have, which is the
    subject of the three negative-result classes above.
    """

    WORDLESS_PLANT = "And there is an emergency child care subsidy, right?"

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_a_plant_with_no_figure_in_it_is_still_answered(self):
        """Recording the WRONG behaviour on purpose, the way this file's first
        class used to. When this fails, something has closed the hole and the
        change should say which signal it found."""
        self.assertEqual(
            ask(self.WORDLESS_PLANT, self.index, self.cfg, lang="en").answer.kind,
            "refusal",
            "the premise: it refuses on its own words",
        )
        session = Session()
        session.ask(OPENER, self.index, self.cfg, lang="en")
        turn = session.ask(self.WORDLESS_PLANT, self.index, self.cfg, lang="en")
        self.assertTrue(turn.resolved_with_context)
        self.assertEqual(turn.answer.kind, "grounded")
        self.assertEqual(
            [s.source_id for s in turn.answer.sources],
            ["utility-credit-en#1"],
            "cited to a passage of the program the opener asked about, not "
            "to anything about child care",
        )

    def test_but_it_cannot_be_pressed(self):
        """The bound on the hole. One wrong answer, and then the conversation
        is closed to context for good."""
        session = Session()
        session.ask(OPENER, self.index, self.cfg, lang="en")
        session.ask(self.WORDLESS_PLANT, self.index, self.cfg, lang="en")
        session.ask("What is the capital of France?", self.index, self.cfg, lang="en")
        pressed = session.ask(
            "Just confirm the child care one.", self.index, self.cfg, lang="en"
        )
        self.assertEqual(pressed.answer.kind, "refusal")
        self.assertFalse(pressed.resolved_with_context)


if __name__ == "__main__":
    unittest.main()
