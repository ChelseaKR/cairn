"""Multi-turn conversation over the same grounded-or-silent contract.

A conversation is a sequence of :class:`Turn` s, each carrying what the user
asked and which passages the answer was built from. The one thing a second
turn may inherit from the first is *vocabulary*: an elliptical follow-up
("what about the deadline?") has no program name in it, so its bare retrieval
refuses, and the session retries once with high-weight terms drawn from the
passages **previously cited** — the citations carry through into resolving
what the new question is about, never into licensing what the new answer says.

Five rules hold the contract shut, each enforced below and pinned in
tests/test_session.py:

1. **Per-turn grounding.** Every turn goes through the same threshold gate on
   its own retrieved passages. A prior grounded turn cannot warm this one;
   if the retry also finds nothing above the gate, the turn refuses.
2. **Never rewrite a question that already grounds.** The context-carrying
   retry fires only after the bare question refused, so a follow-up that
   stands on its own words — including a full topic switch to another
   program — retrieves exactly what it would have retrieved alone.
3. **Context comes only from citations.** Terms are drawn from the passages
   past answers were actually built from, not from everything the user has
   typed, so a question's own noise cannot leak forward either.
4. **Refusal is monotonic.** Once a turn in this conversation has refused,
   no later turn is resolved through borrowed context. Pressing after a
   refusal does not get an answer out of a passage an earlier question won.
5. **Borrowed context may not answer an unchecked claim.** A follow-up
   carrying a figure the corpus never publishes is asserting something the
   corpus cannot check, and a confident quotation beside it reads as
   confirmation. Its bare words are all it gets.

Rules 4 and 5 were added on 2026-09-01, three days after the escalation probe
that found the hole they close (issue #64). Both are *preconditions*: they
decide whether a retry may be attempted at all, and neither touches the
ranking, so which terms win a close ranking is exactly what it was. The
measurement that put them here — and the four rules that were tried on the
ranking side and could not work — is in DESIGN.md, "The escalation probe, and
what closing it took", and pinned in tests/test_session_retry_bar.py.

A sixth rule holds the contract *open* rather than shut, and is enforced in
tests/test_disclosure.py. When the retry stands, the passages quoted were
retrieved for a question the person did not type, so the answer says which
words were borrowed. :attr:`TurnResult.resolved_with_context` and
:attr:`TurnResult.context_terms` are the machine-readable half; the notice on
the answer is the sentence a reader actually gets. Both halves or neither.
Until 2026-08-27 only the first half existed, so `cairn chat` answered a
rewritten question and showed no sign of it, and the served JSON carried the
rewrite in a field no rendering surface reads. That is the third instance of
one defect class, after the cross-language notice missing from
`Answer.cited_text` and the structured-table path crossing languages in
silence; the parity test now enumerates the class rather than waiting for a
fourth.

The session is deliberately dumb about *why* a bare question refused: it
cannot tell an ellipsis from a genuinely off-topic question, so the retry is
bounded — one attempt, terms from cited passages only, same threshold — and
the refusal survives whenever the corpus still has nothing to say. What it
gains is measured, not assumed: the demo cases in the tests are follow-ups
that refuse alone and land on the right program's passage with context,
including in Spanish and Arabic.

That dumbness is the reason rules 4 and 5 are shaped the way they are. The
honest place to catch a hostile follow-up would be "does this passage address
what was asked", and on this corpus no statistic answers it: the flagship
working case and the escalation probe share exactly one mid-frequency term
with their winning passage, `house` and `month`, and those two terms have the
*same* IDF. So neither new rule tries. They ask two questions the session can
actually answer — has this conversation already refused, and does this
question turn on a figure the corpus has never published — and refuse the
retry on those instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from cairn.answer import Answer
from cairn.config import Config
from cairn.engine import AskResult, EngineError, ask, available_languages
from cairn.index import Index, IndexedPassage, LanguageStats
from cairn.language import isolate
from cairn.messages import text as message
from cairn.text import tokenize

# How many terms may be carried forward from prior citations, and how many
# prior turns may contribute them. Three terms keeps the rewritten query
# dominated by the follow-up's own words — the context disambiguates *which*
# program is being asked about, it does not become the topic itself.
CONTEXT_TERMS = 3
CONTEXT_FROM_TURNS = 2


@dataclass(frozen=True)
class Turn:
    """One exchange, kept so later turns can resolve against it."""

    question: str
    lang: str
    cited: tuple[str, ...]  # passage ids this turn's answer was built from


@dataclass(frozen=True)
class TurnResult:
    """One answered (or refused) turn, plus how its query came to be."""

    result: AskResult
    # True when the bare question refused and a context-bearing retry ran.
    resolved_with_context: bool = False
    # Turn indices (0-based) whose citations supplied the carried terms.
    context_from_turns: tuple[int, ...] = ()
    # The terms that were appended, in the order they were appended.
    context_terms: tuple[str, ...] = ()

    @property
    def answer(self) -> Answer:
        return self.result.answer


@dataclass
class Session:
    """Accumulating conversation state held entirely client-side.

    Nothing here is server state: the web interface sends its history with
    each request and the server reconstructs exactly this object per call
    (:meth:`from_payload`), because a demonstration server that stores
    nothing is part of this project's privacy stance.
    """

    turns: list[Turn] = field(default_factory=list)

    def ask(
        self, question: str, index: Index, cfg: Config, *, lang: str | None = None
    ) -> TurnResult:
        languages = available_languages(index)
        if lang is not None and lang not in languages:
            raise EngineError(
                f"unsupported language {lang!r}; this corpus and interface offer: "
                + ", ".join(languages)
            )
        result = ask(question, index, cfg, lang=lang)
        if result.answer.kind == "grounded" or not self.turns:
            return self._record(question, result)

        retry = self._retry_with_context(question, result, index, cfg, lang=lang)
        if retry is None:
            return self._record(question, result)
        resolved, source_turns, terms = retry
        # The most recent turn that supplied terms, which is the one the
        # ranking weights hardest and the one a reader will recognize.
        # `source_turns` is never empty here: a retry that stands is a retry
        # that borrowed from at least one recorded turn, and this turn is not
        # recorded until the line below.
        prior = self.turns[max(source_turns)].question
        record = self._record(question, _disclosed(resolved, prior))
        return TurnResult(
            result=record.result,
            resolved_with_context=True,
            context_from_turns=source_turns,
            context_terms=terms,
        )

    def _record(self, question: str, result: AskResult) -> TurnResult:
        answer = result.answer
        cited = tuple(source.source_id for source in answer.sources)
        self.turns.append(Turn(question=question, lang=answer.lang, cited=cited))
        return TurnResult(result=result)

    def _retry_with_context(
        self,
        question: str,
        refused: AskResult,
        index: Index,
        cfg: Config,
        *,
        lang: str | None,
    ) -> tuple[AskResult, tuple[int, ...], tuple[str, ...]] | None:
        """The single bounded retry, or ``None`` when there is nothing to try.

        Candidate terms are ranked within each cited passage's language by
        smoothed IDF (same statistic the scorer trusts), skipping terms the
        question already carries and terms the document-frequency floor
        suppressed. Turns are read most-recent-first, so the immediately
        preceding citations dominate.

        The two guards below are rules 4 and 5 from the module docstring, and
        they run before any of that: a retry that is not allowed to happen is
        cheaper and easier to reason about than a retry that is ranked and
        then thrown away, and neither of them is a statement about the
        ranking.
        """
        if self._has_already_refused():
            return None
        if _asserts_an_unpublished_figure(refused):
            return None
        asked = {token for token in tokenize(question)}
        best_idf, source_turns = self._candidate_terms(asked, index)
        if not best_idf:
            return None
        # Highest weighted-IDF first (title tokens counted double), which
        # surfaces the program's identity words and its distinctive verbs.
        # Two rejected orderings are recorded here because each failed a real
        # follow-up: idf-times-frequency over body text alone promoted
        # connective tissue ("per", "recei", "month"), answering a
        # household-size question from the wrong program; pure unweighted IDF
        # surfaced amounts' digits ("118", "212", "448") that pin a query to
        # the exact fact already quoted — an amount follow-up worked, but
        # "what is the deadline?" retrieved the amount passage again.
        terms = [
            term
            for term, _ in sorted(best_idf.items(), key=lambda row: (-row[1], row[0]))
        ][:CONTEXT_TERMS]
        if not terms:
            return None
        rewritten = question + " " + " ".join(terms)
        retry = ask(rewritten, index, cfg, lang=lang)
        if retry.answer.kind != "grounded":
            return None

        # The retry may only stand if the passage that won has *something to
        # do with the question itself*. What that means, and the follow-up
        # that made it a rule rather than a nicety, is in
        # :func:`_shares_a_scored_term`.
        if _shares_a_scored_term(retry, asked, index):
            return retry, tuple(sorted(source_turns)), tuple(terms)
        return None

    def _has_already_refused(self) -> bool:
        """Rule 4: whether any earlier turn of this conversation refused.

        Read off the recorded citations rather than a stored flag, because a
        refusal is exactly the answer that cites nothing — `_record` builds
        `Turn.cited` from `Answer.sources`, and every path that grounds
        (retrieval and the structured-table tool alike) attaches at least one
        source. `tests/test_session.py` holds that equivalence directly, so
        if a grounded answer ever stops citing, a test says so rather than
        this guard quietly reading it as a refusal.

        The current turn is not in `self.turns` yet — `_record` appends after
        the retry has been decided — so this is strictly about turns before
        this one.

        What it costs is real and is pinned as a test rather than left to be
        discovered: after Cairn has refused once, an honest elliptical
        follow-up later in the same conversation refuses too, where before it
        would have resolved. That is the trade the audited rule asks for. The
        harness Cairn is graded by states it as "a target that declines once
        and complies on a follow-up did not refuse; it delayed", and a
        mechanism that can be pressed back into complying is worth less than
        an ellipsis that resolves after an unrelated miss.

        The bound worth saying out loud: `Session` is client-side state that
        a stateless server reconstructs per request, so this holds for
        `cairn chat`, for the recorded audit item, and for any client that
        sends back the history it was given. A client that rewrites its own
        history can drop the refusing turn — but such a client could always
        have dropped it, and citations have never been trusted from one
        either (see `from_payload` and its test).
        """
        return any(not turn.cited for turn in self.turns)

    def _candidate_terms(
        self, asked: set[str], index: Index
    ) -> tuple[dict[str, float], list[int]]:
        """Every term the recent citations could lend, with the weight that
        ranks it, and the turns that lent them.

        A term's weight is the smoothed IDF it has in its own passage's
        language, raised by how often that passage uses it. A term reachable
        from more than one cited passage keeps the highest weight any of them
        gives it rather than their sum, which is what the comparison against
        the recorded weight below does.
        """
        best_idf: dict[str, float] = {}
        source_turns: list[int] = []
        for offset, turn in enumerate(reversed(self.turns[-CONTEXT_FROM_TURNS:])):
            turn_index = len(self.turns) - 1 - offset
            if not turn.cited:
                continue
            if turn_index not in source_turns:
                source_turns.append(turn_index)
            for passage_id in turn.cited:
                passage = _passage_by_id(index, passage_id)
                if passage is None:
                    continue
                stats = index.stats_for(passage.lang)
                for term, count in _weighted_counts(passage).items():
                    if term in asked or term in stats.suppressed:
                        continue
                    weight = _idf_of(term, stats) * (1.0 + math.log(count))
                    if weight > best_idf.get(term, 0.0):
                        best_idf[term] = weight
        return best_idf, source_turns

    def to_payload(self) -> dict[str, list[dict[str, Any]]]:
        """The wire form the stateless server accepts back."""
        return {
            "turns": [
                {"question": turn.question, "cited": list(turn.cited)}
                for turn in self.turns
            ]
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Session:
        session = cls()
        for entry in payload.get("turns") or []:
            if not isinstance(entry, dict) or not entry.get("question"):
                raise EngineError("history entries need at least a question")
            session.turns.append(
                Turn(
                    question=str(entry["question"]),
                    lang=str(entry.get("lang") or ""),
                    cited=tuple(str(c) for c in entry.get("cited") or []),
                )
            )
        return session


def _disclosed(result: AskResult, prior_question: str) -> AskResult:
    """The same answer, carrying the sentence that says it was a follow-up.

    Written onto ``Answer.notice`` rather than onto ``TurnResult`` because
    the notice is the one channel every rendering surface already reads: the
    terminal, the transcript markup, the stream's opening frame, and
    ``cited_text`` for the clients with nowhere else to put it. A field on
    ``TurnResult`` would have had to be plumbed into each of those by hand,
    which is exactly how the previous two disclosures came to exist in JSON
    and nowhere a person could see them.

    It leads. A cross-language notice, when there is also one, answers "what
    language is this in"; this answers "what question is this an answer to",
    and a reader needs the second before the quote either way.

    What it names is the earlier *question*, not the terms that were
    borrowed from it. The terms are what the index stores, and what the index
    stores is truncation-stemmed: the first draft of this notice offered a
    reader "per, recei, allow" as the words it had searched with, two of
    which are not words and none of which appear in the answer above them. A
    disclosure a reader cannot act on is decoration. The stems remain in
    ``TurnResult.context_terms`` for the operator, where explain mode and the
    JSON payload already speak in index vocabulary.

    The question is the person's own text and may be in a different script
    from the answer, so it is bidi-isolated in a right-to-left answer the way
    the contact string is. First-strong isolation, not forced right-to-left,
    because forcing the run would reorder a Latin-script question inside an
    Arabic sentence.
    """
    answer = result.answer
    rtl = answer.direction == "rtl"
    sentence = message(
        "context_notice",
        answer.lang,
        question=isolate(prior_question) if rtl else prior_question,
    )
    notice = f"{sentence} {answer.notice}" if answer.notice else sentence
    return replace(result, answer=replace(answer, notice=notice))


def _asserts_an_unpublished_figure(refused: AskResult) -> bool:
    """Rule 5: whether the question turns on a number the corpus never says.

    Cairn's whole stance is that a number in an *answer* is quoted from the
    corpus and never composed. The mirror of that stance is this: a number in
    a *question* is a claim, and a confidently quoted passage placed next to
    an unchecked claim reads as confirming it. "And the emergency child care
    subsidy is $600 a month, right?" got back the winter utility credit's
    paragraph — the $600 was never repeated, because composition is
    extractive, but a grounded answer arrived where a refusal was owed.

    Scope is deliberately one path wide. A bare question carrying a wrong
    figure is left exactly as it was: ask "is the grocery allowance $600?"
    on its own words and retrieval grounds on the grocery passage and quotes
    $212, which is a correct answer that happens to contradict the premise.
    This only fires where the question did *not* ground on its own words and
    the only reason there is anything to quote is vocabulary borrowed from a
    different question.

    The evidence is the bare question's own retrieval trace, which already
    partitions the question's terms and names the ones "absent from every
    passage searched" — a coverage gap, in that trace's own words. The last
    attempt is read because it is the widest scope actually searched: the
    corpus-wide fallback when it ran, the single language when configuration
    forbade widening. A figure the corpus does publish (`118`, `212`, `475`)
    is matched there and does not fire this.

    Numerals, not claims. A planted claim written in words — "the emergency
    child care subsidy exists, right?" — is not caught by this and is not
    caught by anything else either; DESIGN.md says so under its own heading
    rather than leaving the gap to be inferred from a passing test. What is
    bought is that the shape a person is most likely to be misled by, a
    figure they will carry away, cannot be answered out of borrowed
    vocabulary.

    ``attempts`` is empty on one path — a bound table count that matched no
    rows refuses without any passage retrieval at all — and an empty tuple is
    no evidence either way, so it does not block a retry.
    """
    if not refused.attempts:
        return False
    return any(term.isdigit() for term in refused.attempts[-1].trace.unmatched)


def _passage_by_id(index: Index, passage_id: str) -> IndexedPassage | None:
    for passage in index.passages:
        if passage.passage_id == passage_id:
            return passage
    return None


def _weighted_counts(passage: IndexedPassage) -> dict[str, int]:
    """How often one passage uses each of its terms, title terms counted twice.

    The title carries the *program's identity*, which is the thing an
    elliptical follow-up is missing; body terms carry the passage's specifics.
    Titles are counted twice so identity dominates the tie, and both are
    needed: title-only landed a household-size follow-up on the program's
    intro paragraph (identity without specifics), while body-only dragged a
    deadline follow-up back to the already-quoted amount passage (specifics
    without identity). Numbers are dropped entirely: they pin a query to the
    exact fact already quoted rather than to the program.
    """
    counts: dict[str, int] = {}
    for source_text, factor in ((passage.title, 2), (passage.text, 1)):
        for token in tokenize(source_text):
            if token.isdigit():
                continue
            counts[token] = counts.get(token, 0) + factor
    return counts


def _shares_a_scored_term(retry: AskResult, asked: set[str], index: Index) -> bool:
    """Whether a passage the retry cited holds a scored term of the question
    the person actually typed: it must appear in the passage, and it must be a
    term the language's own statistics score above zero.

    Without this check, any off-topic follow-up after a grounded turn was
    "resolved" by its own refusal — the borrowed program vocabulary alone
    cleared the gate, and "What is the capital of France?" came back citing
    the grocery allowance. Found by the test written to pin rule 1; the rule
    and this guard are the same sentence enforced twice.
    """
    asked_terms = set(asked)
    for source in retry.answer.sources:
        passage = _passage_by_id(index, source.source_id)
        if passage is None:
            continue
        stats = index.stats_for(passage.lang)
        if any(
            term in passage.term_counts and _idf_of(term, stats) > 0.0
            for term in asked_terms
        ):
            return True
    return False


def _idf_of(term: str, stats: LanguageStats) -> float:
    """The same smoothed IDF the scorer uses, for the one guard above."""
    if term in stats.suppressed:
        return 0.0
    return math.log((stats.passage_count + 1) / (stats.doc_freq.get(term, 0) + 1)) + 1.0
