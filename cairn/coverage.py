"""Evidence-set coverage: which corpus passages the recorded question set
actually exercises.

Reuses the same `engine.ask` calls `cairn record` makes — the same
`Candidate.accepted` objects the evidence bundle's `items[...].sources` is
built from — so a passage counted here as "reached" is reached by exactly
the mechanism the bundle records, not a second idea of what "reached" means.

This is not a reachability claim. A passage absent from every accepted set
here was never asked about by this question set; it may still be a perfectly
good, retrievable passage nobody happened to write a question for. It writes
nothing — no index, no bundle, no file of any kind — and it is not part of
the audited evidence path; see `cairn record`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.index import Index
from cairn.record import DEFAULT_QUESTIONS, load_questions


@dataclass(frozen=True)
class CoverageReport:
    question_count: int
    passage_count: int
    reached_counts: dict[str, int]
    unreached: tuple[str, ...]


def coverage_report(
    index: Index, cfg: Config, questions_path: str | Path = DEFAULT_QUESTIONS
) -> CoverageReport:
    questions = load_questions(questions_path)
    reached: Counter[str] = Counter()
    for question in questions:
        result = ask(question["prompt"], index, cfg, lang=question["lang"])
        for candidate in result.answer.trace.accepted:
            reached[candidate.passage.passage_id] += 1
    all_ids = {p.passage_id for p in index.passages}
    unreached = tuple(sorted(all_ids - set(reached)))
    return CoverageReport(
        question_count=len(questions),
        passage_count=len(all_ids),
        reached_counts=dict(sorted(reached.items())),
        unreached=unreached,
    )


def render(report: CoverageReport) -> str:
    lines = [
        f"{report.question_count} question(s) exercised "
        f"{len(report.reached_counts)} of {report.passage_count} passage(s)."
    ]
    if report.unreached:
        lines.append(
            f"{len(report.unreached)} passage(s) never appeared in any accepted "
            f"candidate set for this question set (not necessarily unreachable — "
            f"only never asked about here):"
        )
        lines += [f"  {pid}" for pid in report.unreached]
    else:
        lines.append("Every passage was reached by at least one question.")
    return "\n".join(lines)
