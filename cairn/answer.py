"""Answer composition: grounded or refusal — the only two outcomes.

Grounded answers are extractive: the answer text is the accepted passages,
verbatim, in rank order. Every fact in an answer — numeric policy facts
included — therefore appears character-for-character in a cited passage,
so the spec's traceability requirement (R2) holds by construction.

A refusal (spec R3) is a first-class outcome, not an error: it says plainly
that no source covers the question, points at the configured human channel,
and carries no sources and no partial guess. There is no third kind and no
code path that emits answer text without accepted passages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cairn.retrieve import RetrievalTrace


@dataclass(frozen=True)
class Source:
    title: str
    source_id: str  # stable passage id an operator can look up: <doc-id>#<ordinal>


@dataclass(frozen=True)
class Answer:
    kind: Literal["grounded", "refusal"]
    text: str
    sources: tuple[Source, ...]
    trace: RetrievalTrace

    def to_payload(self) -> dict:
        """Machine-readable record (CLI --json; later, the auditor's input)."""
        return {
            "kind": self.kind,
            "text": self.text,
            "sources": [{"title": s.title, "id": s.source_id} for s in self.sources],
            "grounded": self.kind == "grounded",
        }


def _refusal_text(contact: str) -> str:
    return (
        "I don't have a source for that. None of the official documents this "
        "assistant is allowed to answer from cover your question, and I won't guess.\n"
        f"For help from a person, contact {contact}."
    )


def compose(trace: RetrievalTrace, *, max_passages: int, contact: str) -> Answer:
    accepted = trace.accepted
    if not accepted:
        return Answer(kind="refusal", text=_refusal_text(contact), sources=(), trace=trace)

    used = accepted[:max_passages]
    text = "\n\n".join(c.passage.text for c in used)
    sources = tuple(Source(title=c.passage.title, source_id=c.passage.passage_id) for c in used)
    return Answer(kind="grounded", text=text, sources=sources, trace=trace)
