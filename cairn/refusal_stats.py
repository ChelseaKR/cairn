"""Opt-in, local, aggregate-only refusal analytics.

Off by default — `cairn serve` with no `--refusal-stats` flag behaves
exactly as it always has, and nothing here changes that default path. When
an operator opts in, every refusal increments one counter keyed by
*(language, reason code)* — the same machine-stable codes
`cairn ask --explain` already names for the retrieval stage
(`below-threshold`, `no-lexical-overlap`, `no-passages-in-language`; see
`cairn.explain.refusal_reason`) — and the running totals are written to a
JSON file the operator names.

Nothing else about any individual refusal is ever touched: not the question
text, not the client address, not a timestamp, not a count of *when* — only
a running total per language and reason, indistinguishable after the fact
from any other refusal with the same language and reason. That is the whole
point: "how many refusals were a vocabulary gap in Spanish" is a question
this can answer; "what did person X ask at 14:32" is a question it
structurally cannot, because that fact was never kept. This is the same
posture as `cairn/network.py`'s access controls — a small, auditable,
strictly opt-in primitive — turned toward a different question: not "who
may reach the server" but "what do our refusals say about the corpus."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

# In order, worst-first: a vocabulary gap is more actionable than a
# near-miss, and "nothing in this language at all" is the starkest gap of
# the three. Purely for a stable, readable ordering in `render()`; it has no
# effect on counting.
_REASON_ORDER = ("no-passages-in-language", "no-lexical-overlap", "below-threshold")

_REASON_LEGEND = {
    "no-passages-in-language": (
        "the corpus holds nothing at all in this language — a coverage gap, "
        "not a ranking problem."
    ),
    "no-lexical-overlap": (
        "no passage shared even one scoring term with the question — likely "
        "a vocabulary gap between how the corpus and the question say the "
        "same thing, not a ranking one."
    ),
    "below-threshold": (
        "candidates were scored but none cleared the configured threshold — "
        "a near-miss; see `cairn calibrate`."
    ),
}


class RefusalStatsError(ValueError):
    """The stats file at a named path is not this module's own format."""


def _load(path: Path) -> dict[str, dict[str, int]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RefusalStatsError(f"{path} is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise RefusalStatsError(f"{path} is not a refusal-stats object")
    counts: dict[str, dict[str, int]] = {}
    for lang, by_code in raw.items():
        if not isinstance(by_code, dict):
            raise RefusalStatsError(f"{path}: {lang!r} is not an object of counts")
        counts[str(lang)] = {str(code): int(n) for code, n in by_code.items()}
    return counts


def _save(path: Path, counts: dict[str, dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass
class RefusalCounter:
    """The write side: one aggregate counter, backed by a JSON file.

    Loaded from `path` at construction — a missing file starts at all
    zeros, the normal case the first time an operator points `cairn serve`
    at a path that does not exist yet — and the whole file is rewritten
    after every `record()`. Traffic on the deployment this exists for is
    refusals on a small internal server, not a high-throughput API, so a
    full read-under-lock, increment, write-under-lock per refusal is the
    simplest correct thing rather than a premature optimization; the lock
    is what makes it safe under `ThreadingHTTPServer`.
    """

    path: Path
    _counts: dict[str, dict[str, int]] = field(default_factory=dict, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        self._counts = _load(self.path)

    def record(self, lang: str, code: str) -> None:
        with self._lock:
            by_code = self._counts.setdefault(lang, {})
            by_code[code] = by_code.get(code, 0) + 1
            _save(self.path, self._counts)

    def snapshot(self) -> dict[str, dict[str, int]]:
        """A copy of the current counts — for tests; `cairn refusals` reads
        the file directly instead, since it may run against a server in a
        different process."""
        with self._lock:
            return {lang: dict(codes) for lang, codes in self._counts.items()}


@dataclass(frozen=True)
class RefusalReport:
    total: int
    by_language: dict[str, dict[str, int]]


def report(path: Path) -> RefusalReport:
    """The read side: load `path` and total it up. A missing file is an
    error here — unlike `RefusalCounter`, which treats one as the normal
    start of a new file, a path named explicitly to *read* stats from that
    does not exist is almost always a typo or a server that was never
    started with `--refusal-stats`, and this project's convention (see
    `cairn.calibrate`) is to say so rather than silently report zero.
    """
    if not path.is_file():
        raise RefusalStatsError(
            f"no refusal-stats file at {path} — has `cairn serve --refusal-stats` "
            "written to this path yet?"
        )
    counts = _load(path)
    total = sum(n for by_code in counts.values() for n in by_code.values())
    return RefusalReport(total=total, by_language=counts)


def render(rep: RefusalReport) -> str:
    if rep.total == 0:
        return "No refusals recorded yet."
    rows = [
        (lang, code, count)
        for lang, by_code in rep.by_language.items()
        for code, count in by_code.items()
    ]
    rows.sort(
        key=lambda r: (
            _REASON_ORDER.index(r[1]) if r[1] in _REASON_ORDER else len(_REASON_ORDER),
            -r[2],
            r[0],
        )
    )
    lines = [f"{rep.total} refusal(s) recorded, by language and reason:", ""]
    for lang, code, count in rows:
        lines.append(f"  {lang:<4} {code:<24} {count}")
    lines.append("")
    lines.append("Reason codes:")
    for code in _REASON_ORDER:
        lines.append(f"  {code:<24} {_REASON_LEGEND[code]}")
    return "\n".join(lines)
