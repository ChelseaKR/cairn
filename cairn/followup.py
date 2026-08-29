"""Opt-in, local storage for a real refusal-to-human handoff.

`cairn serve` has always pointed a refusal at a static contact string
(`refusal.contact`/`refusal.contact_by_language` in `cairn.toml`) — a phone
number or address printed into the answer text, unchanged by anything the
asker does next. `--followup-store PATH` is the opt-in upgrade past that: a
"Request a follow-up" action on a refusal, only, that captures the asker's
own contact information (and, only if they separately choose to, the
question they asked) so staff can actually reach back out — a real handoff,
not a printed number the asker has to act on themselves.

Two things distinguish this from `cairn/refusal_stats.py`, deliberately:

- It stores individual, actionable records rather than an aggregate count,
  because a handoff has to name someone to hand off to. Three fields, and
  `STORED_FIELDS` below is the whole of it. It cannot
  make the same "structurally cannot hold a question" promise
  `cairn/refusal_stats.py` makes; instead it makes a narrower one, held by
  `cairn/server.py`: the question is stored *only* when the asker checked
  the "include my question" box on that specific submission, never by
  default and never silently.

  This sentence said "a contact and a timestamp" until 2026-08-27, and no
  record has ever carried a timestamp. `docs/followup.md` publishes the
  stored line verbatim and has always been right; `docs/compliance.md`
  reasons about exactly what this file holds for a records-retention review.
  A module docstring inventing a field for a store of real contact
  information is the kind of wrong that a compliance reader would have
  carried away — and the first correction, on 2026-08-27, only rewrote this
  prose to agree with the code, which left the next drift free to happen the
  same way. `STORED_FIELDS` is the fix with something behind it: `record()`
  builds the written line out of that tuple, so a key it does not name is
  not a key this module can write.
- Nothing here is automatic. No follow-up is ever sent unless the asker
  fills in the form themselves and submits it — there is no code path that
  reaches this module from anywhere but that one explicit action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Final

#: The stored record: every key `record()` writes, in the order it writes
#: them, and the whole of it. `docs/followup.md` publishes the resulting line
#: verbatim and `tests/test_followup.py` compares the bytes this produces to
#: that page, so this tuple, the written file and the published example are
#: one fact in three places rather than three claims that agree today.
#:
#: `record()` projects its arguments through this tuple, which is why it is a
#: declaration and not a comment: a field added to the entry and not to this
#: list is silently not written, and a field added here and not supplied is a
#: `KeyError` on the next submission. Either way somebody has to decide, and
#: then move `docs/followup.md`, `docs/compliance.md` and DESIGN.md, which all
#: reason about what an agency ends up holding on the people who contacted it.
#: That is deliberately more friction than adding a dict key, because this
#: dict is somebody's phone number.
STORED_FIELDS: Final[tuple[str, ...]] = ("contact", "lang", "question")


class FollowupStoreError(ValueError):
    """The store file at a named path is not this module's own format, or
    the path an operator named to read from does not exist yet."""


@dataclass
class FollowupStore:
    """The write side: appends one JSON line per submitted request.

    Append-only and lock-guarded — safe under `ThreadingHTTPServer`, where
    more than one submission can arrive at once. Unlike
    `cairn.refusal_stats.RefusalCounter`, there is nothing to read-modify:
    each request is independent, so a plain locked append is sufficient and
    correct with no read-back needed on the write path.
    """

    path: Path
    _lock: Lock = field(default_factory=Lock, init=False)

    def record(self, *, lang: str, contact: str, question: str | None) -> None:
        """Append one line, containing exactly `STORED_FIELDS` in that order.

        The order is the tuple's, not `sort_keys=True`'s. Sorting happened to
        produce the published order and nothing said so, so the published
        example rested on a keyword argument that could be dropped without a
        single test noticing — which is the defect this docstring's own
        module-level correction was supposed to have closed.
        """
        supplied: dict[str, str | None] = {
            "lang": lang,
            "contact": contact,
            "question": question,
        }
        entry = {name: supplied[name] for name in STORED_FIELDS}
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")


@dataclass(frozen=True)
class FollowupRequest:
    index: int  # 1-based position in the file, for an operator to reference
    lang: str
    contact: str
    question: str | None


def load(path: Path) -> tuple[FollowupRequest, ...]:
    """Every request in `path`, in the order they were submitted.

    A missing file is an error, the same convention `cairn.refusal_stats`
    and `cairn.calibrate` both use: a path named explicitly to *read* from
    that does not exist is almost always a typo or a server that was never
    started with `--followup-store`, not an empty queue.
    """
    if not path.is_file():
        raise FollowupStoreError(
            f"no follow-up store at {path} — has `cairn serve --followup-store` "
            "written to this path yet?"
        )
    requests = []
    for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise FollowupStoreError(f"{path}: line {index} is not valid JSON") from exc
        if not isinstance(entry, dict) or "lang" not in entry or "contact" not in entry:
            raise FollowupStoreError(
                f"{path}: line {index} is not a follow-up request object"
            )
        requests.append(
            FollowupRequest(
                index=index,
                lang=str(entry["lang"]),
                contact=str(entry["contact"]),
                question=(
                    str(entry["question"]) if entry.get("question") is not None else None
                ),
            )
        )
    return tuple(requests)


def render(requests: tuple[FollowupRequest, ...]) -> str:
    if not requests:
        return "No follow-up requests recorded yet."
    lines = [f"{len(requests)} follow-up request(s), oldest first:", ""]
    for request in requests:
        lines.append(f"[{request.index}] {request.lang}  {request.contact}")
        if request.question is not None:
            lines.append(f"      question: {request.question}")
        else:
            lines.append("      question: (not shared)")
    lines.append("")
    lines.append(
        "Once a request is handled, remove its line from the store file — this "
        "is a queue, not a permanent log: rerunning `cairn followups` always "
        "shows what is still outstanding."
    )
    return "\n".join(lines)
