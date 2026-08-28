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
  this list is the whole of it: `lang`, `contact`, and `question`. It cannot
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
  carried away, so `tests/test_followup.py` now holds the written keys to
  this list rather than leaving prose to be checked by reading.
- Nothing here is automatic. No follow-up is ever sent unless the asker
  fills in the form themselves and submits it — there is no code path that
  reaches this module from anywhere but that one explicit action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


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
        entry = {
            "lang": lang,
            "contact": contact,
            "question": question,
        }
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
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
