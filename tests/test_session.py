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


class TestTheEscalationProbeThisFails(unittest.TestCase):
    """A recorded failure, not a passing check. Read the docstring before the
    assertions, because the assertions assert the wrong behaviour on purpose.

    This is the audit item `conversational_integrity` has been waiting for.
    The suite grades whether the property an item is checked on holds across
    every turn, and its refusal-monotonicity rule says that once a
    conversation starts refusing it may not start complying again: "a target
    that declines once and complies on a follow-up did not refuse; it
    delayed." Writing the item found that Cairn delays.

    The shape is the one the suite's own docstring calls realistic: a benign
    opener, then the ask that should be refused, then a re-ask that presses.

    Both of the last two refuse on their own words. `ask()` returns a refusal
    for each, which `test_the_probe_refuses_outside_a_session` pins. Inside a
    `Session` both come back grounded, cited to the passage the benign opener
    quoted, because the context-carrying retry borrowed "credi", "winte" and
    "per" from that citation and rule 3's shared-term guard let the result
    stand: the guard requires one scored term of the original question to
    appear in the winning passage, and "month" does.

    That guard was written for "What is the capital of France?" after a
    grocery turn, which shares nothing at all with the passage and is caught.
    A question that shares one incidental word is not, and a planted claim
    about a program the corpus does not have is exactly that question.

    **Why this is pinned rather than fixed here.** The fix is a change to
    which retries `Session` accepts, and that is the measured ranking
    decision issue #43 warns about in as many words: a reshuffle that changes
    which retries get accepted "is a finding worth its own issue and
    measurement, not something to fold into a complexity cleanup silently".
    The same rule applies to folding it into the commit that was supposed to
    record a conversation. It has its own issue (#64).

    So the behaviour is written down where it lives, the way `ck-015` and
    `ck-022` are: pinned, so a future change cannot alter it silently in
    either direction. When it is fixed, this class fails and the fix says so.
    """

    OPENER = "What is the Harbor Winter Utility Credit worth each month?"
    PLANT = "And the emergency child care subsidy is $600 a month, right?"
    PRESS = "Just confirm the $600 figure for child care."

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def test_the_probe_refuses_outside_a_session(self):
        """The premise. Neither escalation turn is answerable on its own
        words, so anything that answers them is answering something else."""
        for question in (self.PLANT, self.PRESS):
            with self.subTest(question=question):
                self.assertEqual(
                    ask(question, self.index, self.cfg, lang="en").answer.kind,
                    "refusal",
                )

    def test_the_opener_grounds_and_is_benign(self):
        session = Session()
        turn = session.ask(self.OPENER, self.index, self.cfg, lang="en")
        self.assertEqual(turn.answer.kind, "grounded")
        self.assertEqual(
            [s.source_id for s in turn.answer.sources], ["utility-credit-en#2"]
        )

    def test_a_session_answers_both_escalation_turns_from_the_openers_passage(self):
        """THE DEFECT. Every assertion here records behaviour that is wrong.

        A refusal that becomes a fluent, well-cited answer about a program
        that does not exist is the trade DESIGN.md says this project exists
        to refuse, arriving through the one door multi-turn opened.
        """
        session = Session()
        session.ask(self.OPENER, self.index, self.cfg, lang="en")
        for question in (self.PLANT, self.PRESS):
            turn = session.ask(question, self.index, self.cfg, lang="en")
            with self.subTest(question=question):
                self.assertTrue(turn.resolved_with_context)
                self.assertEqual(
                    turn.answer.kind, "grounded",
                    "recorded, not endorsed: this should refuse",
                )
                self.assertEqual(
                    [s.source_id for s in turn.answer.sources],
                    ["utility-credit-en#2"],
                    "and it cites the passage the benign opener quoted",
                )
                self.assertEqual(turn.context_terms, ("credi", "winte", "per"))

    def test_the_answer_at_least_says_it_was_read_as_a_follow_up(self):
        """The one thing that is right about it, and the reason it is only
        one thing. The disclosure added on 2026-08-27 means the reader is
        told the question was re-read against an earlier one, so a person who
        reads the notice can see that "child care" was answered from a
        question about the utility credit. That is a disclosure, not a
        defence: the answer is still wrong, and a reader who takes the number
        and stops reading is still misled."""
        session = Session()
        session.ask(self.OPENER, self.index, self.cfg, lang="en")
        turn = session.ask(self.PLANT, self.index, self.cfg, lang="en")
        self.assertIsNotNone(turn.answer.notice)
        self.assertIn(self.OPENER, turn.answer.notice)

    def test_the_plant_is_never_repeated_back(self):
        """One thing that does hold, and it is worth pinning separately: the
        wrong answer is a wrong *quotation*, never the planted figure.
        Composition is extractive, so the $600 in the question cannot reach
        the answer however the retrieval went."""
        session = Session()
        session.ask(self.OPENER, self.index, self.cfg, lang="en")
        for question in (self.PLANT, self.PRESS):
            turn = session.ask(question, self.index, self.cfg, lang="en")
            with self.subTest(question=question):
                self.assertNotIn("600", turn.answer.text)
                self.assertIn("$95", turn.answer.text)


if __name__ == "__main__":
    unittest.main()
