"""Operator explain mode (spec R5): diagnose a bad answer to the right stage.

The question an operator actually has is never "what is the score" — it is
"whose fault is this answer?" Cairn has exactly two stages that can produce a
disappointing result, and this module reports a verdict for each of them
separately:

*Retrieval* either put passages in front of the answer stage or it did not.
*Answer* either had usable evidence and used it, or it was handed nothing.

Because composition is extractive, an answer stage holding evidence cannot
invent or garble a fact — so when retrieval succeeds and the answer is still
wrong, the report says so and names the one composition knob that can drop a
correct passage on the floor: ``retrieval.max_passages``. A trace that showed
only scores would leave that case looking like a retrieval problem.

Every code below is machine-stable; the prose beside it is for humans.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Literal

from cairn.answer import Answer
from cairn.retrieve import Candidate, RetrievalTrace

StageName = Literal["retrieval", "answer"]

# How much of a passage to show beside its score. Long enough to recognize the
# passage, short enough that a dozen candidates still fit on one screen.
EXCERPT_CHARS = 88

# Report body wrap width: fits an 80-column terminal with the two-space indent.
REPORT_WIDTH = 78


@dataclass(frozen=True)
class StageVerdict:
    stage: StageName
    ok: bool
    code: str  # machine-stable identifier
    detail: str  # one or two sentences for a human operator

    def to_payload(self) -> dict:
        return {"stage": self.stage, "ok": self.ok, "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class Diagnosis:
    grounded: bool
    stages: tuple[StageVerdict, ...]
    blame: StageName | None  # the first stage that did not do its job
    dropped: tuple[Candidate, ...]  # accepted passages the answer stage left out

    def stage(self, name: StageName) -> StageVerdict:
        for verdict in self.stages:
            if verdict.stage == name:
                return verdict
        raise KeyError(name)

    def to_payload(self) -> dict:
        return {
            "grounded": self.grounded,
            "blame": self.blame,
            "stages": [s.to_payload() for s in self.stages],
            "dropped": [c.passage.passage_id for c in self.dropped],
        }


def _fmt(score: float) -> str:
    return f"{score:.3f}"


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """One-line, length-bounded preview of a passage. Deterministic."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def _retrieval_verdict(trace: RetrievalTrace) -> StageVerdict:
    accepted = trace.accepted
    if accepted:
        return StageVerdict(
            stage="retrieval",
            ok=True,
            code="passages-accepted",
            detail=(
                f"{len(accepted)} of {len(trace.candidates)} scored candidates cleared "
                f"the {_fmt(trace.threshold)} threshold; best score "
                f"{_fmt(trace.candidates[0].score)}."
            ),
        )
    if not trace.candidates:
        return StageVerdict(
            stage="retrieval",
            ok=False,
            code="no-lexical-overlap",
            detail=(
                "No passage in the index shares a single scoring term with this "
                "question, so nothing was even scored. Either the corpus does not "
                "cover the subject, or the question's vocabulary does not match the "
                "corpus's."
            ),
        )
    best = trace.candidates[0]
    return StageVerdict(
        stage="retrieval",
        ok=False,
        code="below-threshold",
        detail=(
            f"{len(trace.candidates)} candidates were scored and none cleared the "
            f"{_fmt(trace.threshold)} threshold. The best, {best.passage.passage_id}, "
            f"scored {_fmt(best.score)} and was short by "
            f"{_fmt(trace.threshold - best.score)}."
        ),
    )


def _answer_verdict(
    trace: RetrievalTrace, answer: Answer, dropped: tuple[Candidate, ...]
) -> StageVerdict:
    accepted = trace.accepted
    if not accepted:
        return StageVerdict(
            stage="answer",
            ok=True,
            code="no-evidence",
            detail=(
                "The answer stage was handed no passages, so it refused. It could "
                "not have produced text here; look upstream at retrieval."
            ),
        )
    used = len(answer.sources)
    if dropped:
        ids = ", ".join(c.passage.passage_id for c in dropped)
        return StageVerdict(
            stage="answer",
            ok=True,
            code="composed-truncated",
            detail=(
                f"Composed from {used} of {len(accepted)} accepted passages. "
                f"retrieval.max_passages dropped {ids}. If the fact you expected "
                "lives in a dropped passage, this is a composition problem, not a "
                "retrieval one: raise max_passages."
            ),
        )
    return StageVerdict(
        stage="answer",
        ok=True,
        code="composed",
        detail=(
            f"Composed from all {used} accepted passage(s), verbatim. Every fact in "
            "the answer therefore appears in a cited source."
        ),
    )


def diagnose(answer: Answer, *, max_passages: int) -> Diagnosis:
    trace = answer.trace
    dropped = trace.accepted[max_passages:]
    retrieval = _retrieval_verdict(trace)
    composition = _answer_verdict(trace, answer, dropped)
    stages = (retrieval, composition)
    blame: StageName | None = None
    for verdict in stages:
        if not verdict.ok:
            blame = verdict.stage
            break
    return Diagnosis(
        grounded=answer.kind == "grounded", stages=stages, blame=blame, dropped=dropped
    )


def _candidate_rows(trace: RetrievalTrace) -> list[str]:
    if not trace.candidates:
        return ["  (no candidate passage shared a scoring term with the question)"]
    width = max(len(c.passage.passage_id) for c in trace.candidates)
    rows: list[str] = []
    for rank, candidate in enumerate(trace.candidates, start=1):
        verdict = "ACCEPT" if candidate.accepted else "reject"
        passage = candidate.passage
        rows.append(
            f"  {rank:>2}  {_fmt(candidate.score)}  {verdict}  "
            f"{passage.passage_id:<{width}}  [{passage.lang}] {passage.title}"
        )
        rows.append(f"          {excerpt(passage.text)}")
    return rows


def render(answer: Answer, diagnosis: Diagnosis, *, index_summary: str) -> str:
    """The operator's plain-text report. Written to stdout beside the answer."""
    trace = answer.trace
    lines = [
        "=== retrieval trace " + "=" * (REPORT_WIDTH - 20),
        f"Question:  {trace.query}",
        f"Index:     {index_summary}",
        f"Threshold: {_fmt(trace.threshold)} (retrieval.threshold)",
        "",
        f"Candidates ({len(trace.candidates)} scored, ranked):",
        *_candidate_rows(trace),
        "",
    ]
    for step, verdict in enumerate(diagnosis.stages, start=1):
        if verdict.code == "no-evidence":
            status = "NOT REACHED"
        else:
            status = "OK" if verdict.ok else "FAILED"
        lines.append(f"Stage {step} - {verdict.stage}: {status} ({verdict.code})")
        lines.append(
            textwrap.fill(
                verdict.detail, width=REPORT_WIDTH, initial_indent="  ", subsequent_indent="  "
            )
        )
    lines.append("")
    if diagnosis.grounded:
        lines.append(f"Verdict: GROUNDED - {len(answer.sources)} source(s) cited.")
    else:
        lines.append("Verdict: NOT GROUNDED - refusal, no sources.")
    if diagnosis.blame:
        lines.append(f"Diagnose at: {diagnosis.blame}.")
    lines.append("=" * REPORT_WIDTH)
    return "\n".join(lines)


def trace_payload(trace: RetrievalTrace) -> dict:
    """Machine-readable candidate list for ``ask --explain --json``."""
    return {
        "threshold": trace.threshold,
        "candidates": [
            {
                "rank": rank,
                "score": candidate.score,
                "accepted": candidate.accepted,
                "passage_id": candidate.passage.passage_id,
                "doc_id": candidate.passage.doc_id,
                "title": candidate.passage.title,
                "lang": candidate.passage.lang,
                "excerpt": excerpt(candidate.passage.text),
            }
            for rank, candidate in enumerate(trace.candidates, start=1)
        ],
    }
