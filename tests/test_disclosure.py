"""Every disclosure Cairn makes in a field, it also makes in a sentence.

Three defects in this repository's history have been the same defect. Each
time, the machine-readable half of a disclosure was correct and the sentence a
person reads was missing, and each time it was found by somebody reading the
code rather than by anything that could fail:

1. ``Answer.cited_text`` dropped the cross-language notice, so every client
   with no second field to put it in - a terminal, a transcript, the evidence
   bundle - quoted a foreign passage with nothing saying why. DESIGN.md
   records that it "lived through a milestone, and no run of the gate could
   have found it", and then says: "It was fixed by reading the code. The next
   one will not be."
2. The structured-table path bound an English-only table for a Spanish
   question and returned before the notice logic ran. ``cross_language`` was
   already ``True`` on that path the whole time.
3. ``Session`` resolved an elliptical follow-up by rewriting the question,
   recorded ``resolved_with_context`` and ``context_terms`` in the served JSON,
   and printed nothing about it. ``cairn chat`` answered a question the person
   had not typed and showed no sign of having done so.

The second of those was fixed by adding the missing branch, and the third by
adding the missing sentence. Neither fix stops a fourth. What stops a fourth
is a test that knows the whole set of things Cairn says in its own voice and
the whole set of places a person can read them, and checks the cross product -
which is this file.

**The catalogue is the source of truth, not a list kept here.** A message key
carrying ``_notice`` in its name is Cairn speaking about the answer below it.
The name is the whole rule, which is why ``cross_language_notice_partial``
counts: a variant wording of a disclosure is still a disclosure.
:meth:`TestTheScenarioTableIsComplete.test_every_notice_key_has_a_scenario`
reads those keys out of ``cairn.messages`` and requires each one to have a
scenario in ``SCENARIOS``, so a fifth notice added without one fails here
instead of shipping quiet. That is the difference between this test and the
per-feature tests that already exist: ``tests/test_tabular.py`` checks the
notice the table path produces, and ``tests/test_multilingual.py`` checks the
notice the passage path produces, and both of them would have stayed green
through all three defects above, because a test that knows about one notice
cannot notice a missing one.

**The surfaces are enumerated too.** ``SURFACES`` holds every rendering of an
answer a human being reads: the plain-text form for clients with one channel,
the terminal, the transcript markup the served page and its client script both
build, and the event stream. Each is a real renderer imported from the module
that ships it, not a re-implementation here.
"""

import json
import unittest
from html import unescape
from pathlib import Path

from cairn.answer import Answer
from cairn.cli import _render_answer
from cairn.config import Config
from cairn.engine import AskResult, ask
from cairn.index import build_index
from cairn.language import POP_DIRECTIONAL_ISOLATE, endonym_of
from cairn.messages import CATALOGUE, DEFAULT_LANG
from cairn.session import Session
from cairn.stream import format_sse
from cairn.ui.page import turn_markup

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"

# The demo corpus publishes the transit pass in English only, and the Spanish
# grocery document carries the same amounts as the English one, so a question
# made of a bare figure crosses into whichever language holds it.
TABLE_COUNT = "How many programs have a monthly benefit over $100?"
ENGLISH_ONLY = "GoPass"
SHARED_FIGURE = "212"
GROCERY = "How much is the monthly grocery allowance for one person?"
ELLIPTICAL = "what about a household of four people"


def _from_stream(answer: Answer) -> str:
    """What a client consuming the event stream is handed as the notice.

    Read back out of the serialized frames rather than off the ``Answer``,
    because the point of this surface is the wire: a notice that never made it
    into the bytes is a notice the streaming client does not have. Parsing
    also handles the JSON escaping of the quotation marks the context notice
    puts around the earlier question, which a substring search over raw frames
    would trip on.
    """
    from cairn.stream import events

    for frame in (format_sse(event) for event in events(answer)):
        head, _, body = frame.partition("\n")
        if head == "event: start":
            payload = json.loads(body[len("data: ") : body.index("\n\n")])
            return payload["notice"] or ""
    raise AssertionError("the stream emitted no start frame")


# (name, renderer) for every place a person reads an answer. A renderer takes
# the question and the result and returns text the notice must appear in.
SURFACES = (
    # The whole answer for a client with one channel: a terminal, an SMS
    # gateway, a transcript, and the recorded evidence bundle.
    ("cited_text", lambda question, result: result.answer.cited_text),
    # `cairn ask` and `cairn chat` both print this.
    ("terminal", lambda question, result: _render_answer(result)),
    # The served page and its client script build this same structure.
    (
        "transcript",
        lambda question, result: unescape(
            turn_markup(question, result, result.answer.lang)
        ),
    ),
    ("stream", lambda question, result: _from_stream(result.answer)),
)


class Scenario:
    """One way an answer comes to carry a notice, and what it must say.

    ``key`` is the message key the scenario exercises, and it is what the
    completeness test matches against the catalogue. ``build`` returns the
    question and the result, because two of the four surfaces need the
    question as well as the answer to render anything.

    What gets checked on each surface is the whole notice, not a fragment of
    it: a surface that renders half the sentence is the same defect a few
    words later.
    """

    def __init__(self, name, key, build):
        self.name = name
        self.key = key
        self.build = build


def _passage_crossing(index):
    result = ask(ENGLISH_ONLY, index, Config(), lang="es")
    return ENGLISH_ONLY, result


def _passage_crossing_partial(index):
    result = ask(SHARED_FIGURE, index, Config(max_passages=2), lang="ar")
    return SHARED_FIGURE, result


def _table_count(index):
    return TABLE_COUNT, ask(TABLE_COUNT, index, Config())


def _table_crossing(index):
    return TABLE_COUNT, ask(TABLE_COUNT, index, Config(), lang="es")


def _context_resolved(index):
    session = Session()
    session.ask(GROCERY, index, Config())
    turn = session.ask(ELLIPTICAL, index, Config())
    return ELLIPTICAL, turn.result


SCENARIOS = (
    Scenario("a passage in one other language", "cross_language_notice",
             _passage_crossing),
    Scenario("passages in several other languages", "cross_language_notice_partial",
             _passage_crossing_partial),
    Scenario("a count over a table", "table_count_notice", _table_count),
    # The table path reaches the cross-language wording through its own
    # branch, which is the branch that was missing until 2026-08-26. Sharing a
    # key with the passage scenario is deliberate: the completeness test asks
    # whether every key is covered, and two paths reaching one key is two
    # things worth covering, not a duplicate.
    Scenario("a count over a table in another language", "cross_language_notice",
             _table_crossing),
    Scenario("a follow-up resolved from a prior turn", "context_notice",
             _context_resolved),
)


class DisclosureHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)


class TestEveryNoticeReachesEveryReader(DisclosureHarness):
    """The cross product: each notice, on each surface a person reads."""

    def test_the_notice_appears_in_full_on_every_surface(self):
        for scenario in SCENARIOS:
            question, result = scenario.build(self.index)
            notice = result.answer.notice
            with self.subTest(scenario=scenario.name):
                self.assertIsNotNone(
                    notice, "this scenario is supposed to produce a notice"
                )
            for name, render in SURFACES:
                with self.subTest(scenario=scenario.name, surface=name):
                    self.assertIn(
                        notice,
                        render(question, result),
                        f"{name} renders the answer without the sentence that "
                        f"explains it",
                    )

    def test_the_notice_is_in_the_language_of_the_answer(self):
        """A disclosure in a language the reader did not ask in is not one.

        Checked by identity against the catalogue rather than by script, so a
        notice assembled out of two languages' strings fails here too.
        """
        for scenario in SCENARIOS:
            question, result = scenario.build(self.index)
            lang = result.answer.lang
            template = CATALOGUE[lang][scenario.key]
            skeleton = template.split("{")[0]
            with self.subTest(scenario=scenario.name, lang=lang):
                self.assertIn(skeleton, result.answer.notice)


class TestTheScenarioTableIsComplete(DisclosureHarness):
    """The half that makes this file able to fail for a notice nobody wrote.

    Without it, `SCENARIOS` is a list somebody remembered to extend, which is
    exactly what the README's test count was before a test held it.
    """

    def test_every_notice_key_has_a_scenario(self):
        spoken = {key for key in CATALOGUE[DEFAULT_LANG] if "_notice" in key}
        covered = {scenario.key for scenario in SCENARIOS}
        self.assertEqual(
            spoken,
            covered,
            "a message key carrying _notice in its name is Cairn speaking "
            "about the answer below it, and every one needs a scenario here "
            "proving a reader gets it",
        )

    def test_every_language_can_speak_every_notice(self):
        """The parity test in tests/test_multilingual.py covers the catalogue
        as a whole; this states the same thing about the notices specifically,
        so a notice added in English alone fails in the file that is about
        notices reaching people."""
        spoken = {key for key in CATALOGUE[DEFAULT_LANG] if "_notice" in key}
        for lang, catalogue in CATALOGUE.items():
            with self.subTest(lang=lang):
                self.assertTrue(spoken.issubset(catalogue))


class TestACrossingIsNeverSilent(DisclosureHarness):
    """``AskResult.cross_language`` and the notice cannot disagree.

    Stated over a grid rather than over hand-picked answers, because both
    cross-language defects were paths nobody had thought to point a test at.
    ``cross_language`` is derived from the sources the answer actually
    carries, so it is true exactly when there is something to disclose, and
    the notice has to be there whenever it is - on the passage path, on the
    table path, and on whatever path is added next.
    """

    GRID = (
        (ENGLISH_ONLY, "es", Config()),
        (ENGLISH_ONLY, "ar", Config()),
        (ENGLISH_ONLY, "fr", Config()),
        (SHARED_FIGURE, "ar", Config()),
        (SHARED_FIGURE, "ar", Config(max_passages=2)),
        (SHARED_FIGURE, "en", Config(max_passages=2)),
        (TABLE_COUNT, "es", Config()),
        (TABLE_COUNT, "ar", Config()),
        (TABLE_COUNT, "fr", Config()),
        (TABLE_COUNT, "en", Config()),
        (GROCERY, "en", Config()),
        (GROCERY, "es", Config()),
    )

    def test_a_foreign_source_is_always_named(self):
        crossings = 0
        for question, lang, cfg in self.GRID:
            result = ask(question, self.index, cfg, lang=lang)
            if not result.cross_language:
                continue
            crossings += 1
            with self.subTest(question=question, lang=lang):
                self.assertIsNotNone(
                    result.answer.notice,
                    "the answer quotes a source in another language and says "
                    "nothing about it",
                )
                for code in {s.lang for s in result.answer.sources}:
                    if code == result.answer.lang:
                        continue
                    self.assertIn(endonym_of(code), result.answer.notice)
        self.assertGreaterEqual(
            crossings, 4, "this grid stopped exercising the crossing at all"
        )

    def test_an_answer_with_nothing_foreign_in_it_claims_nothing(self):
        """The mirror image, so the guard above cannot be satisfied by a
        notice bolted onto every answer."""
        for question, lang, cfg in self.GRID:
            result = ask(question, self.index, cfg, lang=lang)
            if result.cross_language or result.answer.notice is None:
                continue
            with self.subTest(question=question, lang=lang):
                for code in CATALOGUE:
                    if code == result.answer.lang:
                        continue
                    self.assertNotIn(endonym_of(code), result.answer.notice)


class TestAResolvedFollowUpIsNeverSilent(DisclosureHarness):
    """``TurnResult.resolved_with_context`` and the notice cannot disagree.

    The third instance of the class, stated the way the first two are: the
    field is the machine-readable half, and a turn that carries it must carry
    the sentence too.
    """

    # Each follow-up refuses on its own words and resolves against the
    # opener's citations. Verified in both directions by
    # `test_every_follow_up_here_still_needs_its_context`, so a corpus edit
    # that makes one of them stand alone fails loudly rather than quietly
    # emptying this class out.
    CONVERSATIONS = (
        ("en", GROCERY, ELLIPTICAL),
        ("es", "Cuanto recibe un hogar de una persona del subsidio de alimentos?",
         "que pasa con cuatro miembros"),
        ("ar", "كم تحصل الأسرة المكونة من شخص واحد شهريًا من مخصص البقالة؟",
         "وماذا عن أربعة أشخاص"),
    )

    def test_every_follow_up_here_still_needs_its_context(self):
        """The premise of the class: bare, each follow-up has no answer."""
        for lang, _opener, followup in self.CONVERSATIONS:
            with self.subTest(lang=lang):
                bare = ask(followup, self.index, Config(), lang=lang)
                self.assertEqual(bare.answer.kind, "refusal")

    def conversations(self):
        for lang, opener, followup in self.CONVERSATIONS:
            session = Session()
            first = session.ask(opener, self.index, Config(), lang=lang)
            turn = session.ask(followup, self.index, Config(), lang=lang)
            yield lang, opener, followup, first, turn

    def test_a_rewritten_question_is_disclosed_with_the_question_it_borrowed_from(self):
        resolved = 0
        for lang, opener, _followup, _first, turn in self.conversations():
            if not turn.resolved_with_context:
                continue
            resolved += 1
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    turn.answer.notice,
                    "the answer was found for a question the person did not "
                    "type, and says nothing about it",
                )
                # The earlier question, verbatim. In a right-to-left answer it
                # arrives inside a bidi isolate, so the closing mark is
                # stripped before comparing rather than the text loosened.
                self.assertIn(
                    opener,
                    turn.answer.notice.replace(POP_DIRECTIONAL_ISOLATE, ""),
                )
        self.assertEqual(
            resolved,
            len(self.CONVERSATIONS),
            "every conversation here is supposed to exercise the retry",
        )

    def test_a_follow_up_that_stood_on_its_own_claims_no_rewrite(self):
        """The mirror image. Rule 2 says a question that grounds is never
        rewritten, so it must not carry the sentence that says it was."""
        session = Session()
        session.ask(GROCERY, self.index, Config())
        turn = session.ask("when do applications close", self.index, Config())
        self.assertFalse(turn.resolved_with_context)
        skeleton = CATALOGUE["en"]["context_notice"].split("{")[0]
        self.assertNotIn(skeleton, turn.answer.cited_text)

    def test_the_disclosure_does_not_disturb_the_quoted_text(self):
        """`Answer.text` is byte-for-byte corpus content, and a notice is not
        corpus content. The guarantee that survived the table tool has to
        survive this too."""
        for lang, _opener, _followup, _first, turn in self.conversations():
            answer = turn.answer
            self.assertEqual(answer.kind, "grounded")
            with self.subTest(lang=lang):
                self.assertEqual(
                    answer.text, "\n\n".join(s.text for s in answer.sources)
                )
                self.assertNotIn(answer.notice, answer.text)

    def test_the_machine_readable_half_still_carries_the_terms(self):
        """The stems stay where an operator reads them. The notice names the
        earlier question instead, because the stems are index vocabulary
        ("per", "recei", "allow") and two of those are not words."""
        session = Session()
        session.ask(GROCERY, self.index, Config())
        turn = session.ask(ELLIPTICAL, self.index, Config())
        self.assertTrue(turn.resolved_with_context)
        self.assertTrue(turn.context_terms)
        self.assertNotIn(", ".join(turn.context_terms), turn.answer.notice)
        self.assertIn(GROCERY, turn.answer.notice)


class TestTheDisclosureSurvivesTheWire(DisclosureHarness):
    def test_a_session_rebuilt_from_a_payload_discloses_the_same_thing(self):
        """The server reconstructs a `Session` per request and stores nothing,
        so the disclosure has to be derivable from the payload the client sent
        back rather than from state the server kept."""
        live = Session()
        live.ask(GROCERY, self.index, Config())
        rebuilt = Session.from_payload(live.to_payload())
        here = live.ask(ELLIPTICAL, self.index, Config())
        there = rebuilt.ask(ELLIPTICAL, self.index, Config())
        self.assertTrue(here.resolved_with_context)
        self.assertEqual(here.answer.notice, there.answer.notice)
        self.assertEqual(here.answer.cited_text, there.answer.cited_text)


class TestTheResultTypesCarryNoUndisclosedSignal(DisclosureHarness):
    """A new field on either result type is a new thing Cairn knows about its
    own answer, and the question "does a reader need to be told" has to be
    asked when it is added rather than after somebody notices.

    Modelled on `tests/test_config_report.py`, which holds
    `diff_from_defaults` to `fields(Config)` for the same reason: a hand-kept
    list of what matters silently omits whatever was added last.
    """

    # Every field, with the reason it needs no sentence of its own or the
    # notice that carries it.
    ASK_RESULT = {
        "answer": "the answer itself, which every surface renders",
        "detection": "operator diagnostics; explain mode prints it",
        "attempts": "operator diagnostics; explain mode prints it",
        "tool": "disclosed by table_count_notice",
    }
    TURN_RESULT = {
        "result": "the AskResult, covered above",
        "resolved_with_context": "disclosed by context_notice",
        "context_from_turns": "disclosed by context_notice",
        "context_terms": "operator detail; context_notice names the question",
    }

    def test_every_field_has_been_asked_the_question(self):
        from dataclasses import fields

        from cairn.session import TurnResult

        for cls, accounted in ((AskResult, self.ASK_RESULT),
                               (TurnResult, self.TURN_RESULT)):
            with self.subTest(type=cls.__name__):
                self.assertEqual(
                    {f.name for f in fields(cls)},
                    set(accounted),
                    "a new field here is a new thing Cairn knows about its "
                    "own answer: either a reader is told, or say here why "
                    "not",
                )


if __name__ == "__main__":
    unittest.main()
