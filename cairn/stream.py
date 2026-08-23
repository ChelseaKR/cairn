"""Streaming an answer as events, without changing what the answer is.

Cairn composes before it speaks: :func:`cairn.engine.ask` returns a complete
:class:`~cairn.answer.Answer`, and this module slices that finished object
into an ordered event sequence for clients that want to render progress
rather than wait for one payload. There is no incremental generation here to
make faster — composition is extractive and milliseconds cheap — so streaming
is purely presentational, and its contract is exactness:

1. **Every event derives from the composed ``Answer`` alone.** No index, no
   configuration, no second call into the engine. A client that ignores the
   stream and a client that consumes it have been given the same answer by
   construction.
2. **Spans precede text.** Each cited passage is emitted as a ``span`` event
   before the first ``text`` frame, so a renderer can build the sources list,
   resolve languages and directions, and attach inline citation anchors
   before any quote arrives — the order the accessibility contract wants,
   not the order bytes happen to sit in.
3. **Chunking is deterministic.** Text splits on sentence boundaries only;
   the concatenation of all ``text`` payloads equals ``Answer.text`` byte for
   byte, always. Two streams for one answer are identical, which is what
   makes the sequence testable at all.
4. **A refusal streams too.** It has no spans and carries no notice — the
   same shape rules as ever — but its text flows through the same chunking,
   because a slow channel is the worst place to drop the explanation of why
   there is no answer.

Events are plain dicts; :func:`format_sse` renders them as server-sent
events for the demo server, and the CLI prints the same rendering. Both
surfaces therefore stream *identically*, for the same reason the CLI and the
web interface once drifted apart and tests were written to make that drift
impossible twice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from cairn.answer import Answer

# Sentence-terminal punctuation across the interface languages: Latin . ! ?,
# Arabic ؟, the ellipsis character, and the closing forms that can follow a
# terminator. A break happens only where a terminator meets whitespace or end
# of text, so URLs-like runs ("555-0142.") stay inside their sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?\u061f\u2026])\s+")


def _chunks(text: str) -> list[str]:
    """Sentence-boundary pieces whose concatenation is ``text`` exactly.

    Slicing rather than splitting, deliberately: ``re.split`` discards the
    matched whitespace between sentences, and a stream that silently ate
    every inter-sentence space would fail the byte-exactness contract this
    module exists to hold.
    """
    if not text:
        return []
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        if end > start:
            parts.append(text[start:end])
            start = end
    if start < len(text):
        parts.append(text[start:])
    return parts


def events(answer: Answer) -> Iterator[dict]:
    """The ordered event sequence for one composed answer."""
    yield {
        "event": "start",
        "kind": answer.kind,
        "lang": answer.lang,
        "dir": answer.direction,
        "notice": answer.notice,
    }
    # Spans first, whatever the kind — a grounded answer's citations land in
    # the client before its first quoted word. A refusal yields none, because
    # a refusal cites nothing and inventing empty spans would suggest waiting.
    for source in answer.sources:
        yield {"event": "span", "source": source.to_payload()}
    for chunk in _chunks(answer.text):
        yield {"event": "text", "text": chunk}
    yield {
        "event": "end",
        "sources": [source.source_id for source in answer.sources],
    }


def format_sse(event: dict) -> str:
    """One event as a server-sent-events frame. Keys sort, so the same event
    always renders as the same bytes."""
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return f"event: {event['event']}\ndata: {payload}\n\n"


def sse_stream(answer: Answer) -> Iterator[str]:
    """The full frame sequence for an answer."""
    for event in events(answer):
        yield format_sse(event)
