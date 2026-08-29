"""#64: why the shared-term guard cannot be fixed by raising its bar.

`Session._retry_with_context` ends with a guard: a context-resolved retry may
only stand if the winning passage contains at least one *scored* term of the
original follow-up. It was measured against `"What is the capital of France?"`
asked after a grounded grocery turn, which shares nothing with any candidate
and is correctly refused.

#64 is a case it lets through. A three-turn escalation probe -- a benign
opener, then a planted claim about a program the corpus does not have, then a
re-ask that presses -- refuses on both escalation turns when each question is
asked alone, and comes back **grounded, citing the opener's passage**, inside a
session. The person asking about an emergency child care subsidy is answered
about the winter utility credit. `month` is a scored term of turn two and it
appears in `utility-credit-en#2`, so the guard is satisfied.

`#64` proposes where a fix might live:

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

This file pins that. It is a negative result held as a test, so that the day a
corpus or a scorer makes the separation possible is a day something fails
rather than a day nobody notices. Each assertion states the domination it
found, in the direction that makes a fix impossible.

Two rules already measured and recorded elsewhere are re-measured here so the
whole family sits in one place:

- **two shared terms instead of one** -- fixes the probe, breaks the flagship
  (recorded on #64 as a comment, and by PR #65);
- **reject a retry whose winner is a passage the previous turn already cited**
  -- #64 calls this "predictably worse ... by construction"; it is measured
  here rather than predicted, and the prediction was right.

Overlaps deliberately with `TestTheEscalationProbeThisFails` on PR #65's
branch, which pins the same behaviour. If both land, the duplication is two
tests asserting one fact and either may be removed; what is not duplicated is
everything below the first class.
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


class TestTheEscalationProbeIsStillWrong(unittest.TestCase):
    """The defect, reproduced. Pinned so it cannot change unnoticed in either
    direction -- becoming correct without a recorded fix is as much a surprise
    as becoming worse."""

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

    def test_a_session_answers_them_from_the_openers_passage(self):
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
                # Recording the WRONG behaviour on purpose. See the module
                # docstring, and `tests/test_session.py`'s own convention.
                self.assertEqual(turn.answer.kind, "grounded")
                self.assertTrue(turn.resolved_with_context)
                self.assertEqual(
                    [source.source_id for source in turn.answer.sources],
                    ["utility-credit-en#2"],
                )

    def test_the_plant_never_reaches_the_answer(self):
        """What does hold, and why the failure is a wrong citation rather than
        a fabricated number: composition is extractive, so the planted $600
        cannot be repeated back. The answer quotes $95."""
        session = Session()
        session.ask(OPENER, self.index, self.cfg)
        turn = session.ask(ESCALATION_TWO, self.index, self.cfg)
        self.assertNotIn("600", turn.answer.text)
        self.assertIn("$95", turn.answer.text)


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
        than predicted -- both the flagship and the probe resolve to exactly
        the passage their opener cited, so the rule cannot tell them apart.
        """
        for opener, follow_up in ((GROCERY, FLAGSHIP), (OPENER, ESCALATION_TWO)):
            with self.subTest(follow_up=follow_up):
                session = Session()
                first = session.ask(opener, self.index, self.cfg)
                previously_cited = {s.source_id for s in first.answer.sources}
                turn = session.ask(follow_up, self.index, self.cfg)
                won = {s.source_id for s in turn.answer.sources}
                self.assertTrue(won, "both resolve to something today")
                self.assertEqual(
                    won,
                    previously_cited,
                    "the rule would reject this retry, and it must only reject "
                    "one of the two",
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


if __name__ == "__main__":
    unittest.main()
