"""Answer composition: grounded or refusal — the only two outcomes.

Grounded answers are extractive: the answer text is the accepted passages,
verbatim, in rank order. Every fact in an answer — numeric policy facts
included — therefore appears character-for-character in a cited passage, so
the spec's traceability requirement (R2) holds by construction. That is also
why nothing here translates: a translated amount is an unsourced amount, so a
passage in another language is quoted in its own language and labelled with
it.

A refusal (spec R3) is a first-class outcome, not an error: it says plainly
that no source covers the question, points at the configured human channel,
and carries no sources and no partial guess. There is no third kind and no
code path that emits answer text without accepted passages.

The refusal wording arrives already localized (see :mod:`cairn.messages`).
This module composes; it does not speak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cairn.language import Direction, direction_of
from cairn.retrieve import RetrievalTrace

# Cairn names a passage `<doc-id>#<ordinal>`. An inline citation marker is a
# different, narrower grammar — square brackets around an identifier with no
# "#" in it — so a marker writes the ordinal separator as a dot. The canonical
# identifier is unchanged and is what `Source.source_id` and the sources list
# carry; this affects the marker text and nothing else.
CITATION_SEPARATOR = "."


def citation_marker(source_id: str) -> str:
    """The inline marker form of a passage id."""
    return source_id.replace("#", CITATION_SEPARATOR)


@dataclass(frozen=True)
class Source:
    """A cited passage: what was quoted, from where, in what language.

    The quoted text lives here rather than only in ``Answer.text`` because a
    renderer has to know the language of each quote separately. An English
    passage cited in an Arabic answer needs its own ``lang`` and ``dir``, or a
    screen reader announces English in an Arabic voice and the browser lays it
    out backwards. ``Answer.text`` is these quotes joined, and stays the
    canonical plain-text form.
    """

    title: str
    source_id: str  # stable passage id an operator can look up: <doc-id>#<ordinal>
    lang: str
    text: str

    @property
    def direction(self) -> Direction:
        return direction_of(self.lang)

    def to_payload(self) -> dict:
        return {
            "title": self.title,
            "id": self.source_id,
            "lang": self.lang,
            "dir": self.direction,
            "text": self.text,
        }


@dataclass(frozen=True)
class Answer:
    kind: Literal["grounded", "refusal"]
    text: str
    sources: tuple[Source, ...]
    trace: RetrievalTrace
    lang: str
    # Said in Cairn's own voice, above the quoted passages — never mixed into
    # the answer text, which stays byte-for-byte corpus content.
    notice: str | None = None

    @property
    def direction(self) -> Direction:
        return direction_of(self.lang)

    @property
    def cited_text(self) -> str:
        """The answer as one block of plain text with its citations in it.

        The structured form above is richer, and any client that can render a
        sources list should use it. This is for the clients that cannot: a
        terminal, a transcript, a text channel — and the evidence bundle,
        whose inline-citation grammar is exactly this. It lives here rather
        than in the recorder because it used to live in the recorder, and a
        text shape only the recorder could produce is a text shape the audit
        graded and no user of the served interface could ever obtain. That
        gap was invisible until the audit was pointed at the running server.

        A refusal cites nothing and is returned unchanged: appending an empty
        marker line to a refusal would be an answer shape on a non-answer.
        """
        if not self.sources:
            return self.text
        marks = " ".join(f"[{citation_marker(s.source_id)}]" for s in self.sources)
        return f"{self.text}\n{marks}"

    def to_payload(self) -> dict:
        """Machine-readable record (CLI --json, the web interface, and the
        audit interlock's input)."""
        return {
            "kind": self.kind,
            "text": self.text,
            "cited_text": self.cited_text,
            "sources": [s.to_payload() for s in self.sources],
            "grounded": self.kind == "grounded",
            "lang": self.lang,
            "dir": self.direction,
            "notice": self.notice,
        }


def compose(
    trace: RetrievalTrace,
    *,
    max_passages: int,
    refusal_text: str,
    lang: str,
    notice: str | None = None,
) -> Answer:
    accepted = trace.accepted
    if not accepted:
        return Answer(
            kind="refusal", text=refusal_text, sources=(), trace=trace, lang=lang
        )

    used = accepted[:max_passages]
    text = "\n\n".join(c.passage.text for c in used)
    sources = tuple(
        Source(
            title=c.passage.title,
            source_id=c.passage.passage_id,
            lang=c.passage.lang,
            text=c.passage.text,
        )
        for c in used
    )
    return Answer(
        kind="grounded", text=text, sources=sources, trace=trace, lang=lang, notice=notice
    )
