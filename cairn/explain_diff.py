"""A/B comparison of one question's retrieval trace across two configs
and/or indexes.

Calls `engine.ask` and `explain.diagnose` twice — never a second scoring
implementation — and diffs the two results: did the verdict flip, did the
blame stage flip, did the accepted candidate set change, how did shared
candidates' scores move. This is a single-question tuning aid ("if I raise
the threshold, does this known-good question still pass?"), not a gate: see
`cairn.record_diff` for the same caveat applied to the whole evidence set,
and `./plumbline-gate.sh` for what actually decides pass or fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn.config import Config
from cairn.engine import ask
from cairn.explain import diagnose
from cairn.index import Index


@dataclass(frozen=True)
class ComparisonSide:
    verdict: str  # "grounded" | "refusal"
    blame: str | None
    accepted: tuple[str, ...]  # cited passage ids, in order
    scores: dict[str, float]  # every scored candidate across every attempt


def _side(question: str, index: Index, cfg: Config, lang: str | None) -> ComparisonSide:
    result = ask(question, index, cfg, lang=lang)
    answer = result.answer
    diagnosis = diagnose(answer, max_passages=cfg.max_passages)
    scores = {
        candidate.passage.passage_id: candidate.score
        for attempt in result.attempts
        for candidate in attempt.trace.candidates
    }
    return ComparisonSide(
        verdict=answer.kind,
        blame=diagnosis.blame,
        accepted=tuple(c.passage.passage_id for c in answer.trace.accepted),
        scores=scores,
    )


@dataclass(frozen=True)
class Comparison:
    question: str
    a: ComparisonSide
    b: ComparisonSide


def compare(
    question: str,
    index_a: Index,
    cfg_a: Config,
    index_b: Index,
    cfg_b: Config,
    *,
    lang: str | None = None,
) -> Comparison:
    return Comparison(
        question=question,
        a=_side(question, index_a, cfg_a, lang),
        b=_side(question, index_b, cfg_b, lang),
    )


def render(comparison: Comparison, *, label_a: str = "A", label_b: str = "B") -> str:
    a, b = comparison.a, comparison.b
    lines = [f"Question: {comparison.question}", ""]
    for label, side in ((label_a, a), (label_b, b)):
        accepted = ", ".join(side.accepted) or "(none)"
        lines.append(f"{label}: {side.verdict}  blame={side.blame}  accepted=[{accepted}]")
    lines.append("")

    flips = []
    if a.verdict != b.verdict:
        flips.append(f"VERDICT FLIP: {a.verdict} -> {b.verdict}")
    if a.blame != b.blame:
        flips.append(f"BLAME FLIP: {a.blame} -> {b.blame}")
    added = set(b.accepted) - set(a.accepted)
    removed = set(a.accepted) - set(b.accepted)
    if added:
        flips.append(f"newly accepted: {', '.join(sorted(added))}")
    if removed:
        flips.append(f"no longer accepted: {', '.join(sorted(removed))}")
    lines.extend(flips or ["No change in verdict, blame, or the accepted set."])

    shared = sorted(set(a.scores) & set(b.scores))
    moved = [
        (pid, a.scores[pid], b.scores[pid]) for pid in shared if a.scores[pid] != b.scores[pid]
    ]
    if moved:
        lines.append("")
        lines.append("score deltas (shared candidates only):")
        lines += [f"  {pid}: {sa:.3f} -> {sb:.3f} ({sb - sa:+.3f})" for pid, sa, sb in moved]

    lines.append("")
    lines.append(
        "This is a single-question tuning aid, not a gate. Run `cairn record` and "
        "./plumbline-gate.sh for a real verdict."
    )
    return "\n".join(lines)
