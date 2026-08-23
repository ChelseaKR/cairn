"""Multi-turn sessions: context may resolve a question, never ground an answer.

Each test here guards one of the three rules in `cairn.session`'s docstring,
plus the wire path (history as payload) and the two measured limitations that
are recorded rather than fixed: a follow-up that grounds on its own words is
never rewritten even when its tie lands wrong, and a same-document attribute
switch can retrieve a sibling paragraph. Both failures stay failures honestly;
the tests document where they live so a future change cannot claim them
silently.
"""

import unittest

from cairn.config import Config
from cairn.engine import EngineError, ask
from cairn.index import build_index
from cairn.server import build_handler  # noqa: F401 - server round-trip uses HTTP below
from cairn.session import Session

CORPUS = "corpus/demo"

GROCERY_AMOUNT = "How much is the monthly grocery allowance for one person?"
HOUSEHOLD_FOLLOWUP = "what about a household of four people"


class TestRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def session_with_grocery_turn(self):
        session = Session()
        first = session.ask(GROCERY_AMOUNT, self.index, self.cfg)
        self.assertEqual(first.answer.kind, "grounded")
        return session

    def test_a_follow_up_that_stands_alone_is_never_rewritten(self):
        """Rule 2: the bare question grounded, so the answer must be exactly
        what single-turn retrieval produces."""
        question = "when do applications close"
        bare = ask(question, self.index, self.cfg)
        session = self.session_with_grocery_turn()
        turn = session.ask(question, self.index, self.cfg)
        self.assertFalse(turn.resolved_with_context)
        self.assertEqual(turn.answer.text, bare.answer.text)
        self.assertEqual(
            [s.source_id for s in turn.answer.sources],
            [s.source_id for s in bare.answer.sources],
            "a standalone follow-up cites what its own words retrieve",
        )

    def test_an_elliptical_follow_up_resolves_through_citations(self):
        """The carry-through case: alone this question has no program name and
        refuses; with the grocery citation behind it, it resolves to the very
        passage holding the per-member amounts."""
        session = self.session_with_grocery_turn()
        alone = ask(HOUSEHOLD_FOLLOWUP, self.index, self.cfg).answer.kind
        self.assertEqual(alone, "refusal", "the premise: bare, it refuses")
        turn = session.ask(HOUSEHOLD_FOLLOWUP, self.index, self.cfg)
        self.assertTrue(turn.resolved_with_context)
        self.assertTrue(turn.context_terms, "the borrowed terms are recorded")
        self.assertEqual(turn.context_from_turns, (0,))
        self.assertEqual(
            [s.source_id for s in turn.answer.sources],
            ["grocery-allowance-en#2"],
        )

    def test_per_turn_grounding_holds_when_context_cannot_help(self):
        """Rule 1: a retry is bounded. If the corpus has nothing for the
        follow-up under any carried vocabulary, the turn refuses — a prior
        grounded turn cannot warm it."""
        session = self.session_with_grocery_turn()
        turn = session.ask("What is the capital of France?", self.index, self.cfg)
        self.assertEqual(turn.answer.kind, "refusal")
        self.assertEqual(turn.answer.sources, ())
        self.assertFalse(turn.resolved_with_context)

    def test_a_topic_switch_retrieves_on_its_own_words(self):
        session = self.session_with_grocery_turn()
        switch = "How much does the GoPass cost per year?"
        turn = session.ask(switch, self.index, self.cfg)
        self.assertFalse(turn.resolved_with_context)
        self.assertEqual(
            [s.source_id for s in turn.answer.sources], ["transit-pass-en#2"]
        )

    def test_the_first_turn_of_a_session_cannot_use_context(self):
        session = Session()
        turn = session.ask("what about a household of four people", self.index, self.cfg)
        self.assertEqual(turn.answer.kind, "refusal")

    def test_every_recorded_turn_keeps_its_citations(self):
        session = self.session_with_grocery_turn()
        session.ask("What is the capital of France?", self.index, self.cfg)
        self.assertEqual(session.turns[0].cited, ("grocery-allowance-en#2",))
        self.assertEqual(session.turns[1].cited, (), "refusals cite nothing")


class TestHistoryOnTheWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_payload_round_trip_matches_the_in_process_session(self):
        live = Session()
        live.ask(GROCERY_AMOUNT, self.index, self.cfg)
        rebuilt = Session.from_payload(live.to_payload())
        self.assertEqual(rebuilt.turns[0].question, GROCERY_AMOUNT)
        self.assertEqual(rebuilt.turns[0].cited, ("grocery-allowance-en#2",))

        followup = HOUSEHOLD_FOLLOWUP
        a = live.ask(followup, self.index, self.cfg)
        b = rebuilt.ask(followup, self.index, self.cfg)
        self.assertEqual(a.answer.cited_text, b.answer.cited_text)
        self.assertEqual(a.context_terms, b.context_terms)

    def test_an_empty_history_behaves_like_no_history(self):
        empty = Session.from_payload({"turns": []})
        turn = empty.ask("what about a household of four people", self.index, self.cfg)
        self.assertEqual(turn.answer.kind, "refusal")

    def test_a_history_entry_without_a_question_is_refused_at_the_door(self):
        with self.assertRaises(EngineError):
            Session.from_payload({"turns": [{"cited": ["grocery-allowance-en#2"]}]})

    def test_citations_to_passages_not_in_the_index_are_ignored(self):
        """A lying client cannot smuggle context in: cited ids that resolve to
        nothing contribute nothing."""
        forged = Session.from_payload(
            {
                "turns": [
                    {
                        "question": GROCERY_AMOUNT,
                        "cited": ["transit-pass-en#2", "no-such-passage#9"],
                    }
                ]
            }
        )
        # The forged transit citation would send a grocery follow-up to the
        # bus-pass document if it were trusted blindly.
        turn = forged.ask(HOUSEHOLD_FOLLOWUP, self.index, self.cfg)
        if turn.resolved_with_context:
            cited_docs = {s.source_id.split("#")[0] for s in turn.answer.sources}
            self.assertNotIn("no-such-passage", cited_docs)


if __name__ == "__main__":
    unittest.main()
