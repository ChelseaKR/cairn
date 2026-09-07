"""Operator explain mode (spec R5): diagnose a bad answer to the right stage.

The question an operator actually has is never "what is the score" — it is
"whose fault is this answer?" Cairn has exactly two stages that can produce a
disappointing result, and this module reports a verdict for each of them
separately:

*Retrieval* either put passages in front of the answer stage or it did not.
*Answer* either had usable evidence and used it, or it was handed nothing.

When a language restriction is in play the report shows every retrieval
attempt, including the widened cross-language one, so the operator sees the
filter that was applied rather than a candidate list that quietly omits most
of the corpus. A jurisdiction restriction is shown the same way: every rung
of the widening ladder is a labelled attempt, so "answered from the state
page" and "the county page lost on score" are two different pictures rather
than one candidate list with no layer on it.

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
from typing import Any, Literal

from cairn.answer import Answer
from cairn.engine import AskResult
from cairn.readability import Measurement, measure
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

    def to_payload(self) -> dict[str, Any]:
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

    def to_payload(self) -> dict[str, Any]:
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
    if not trace.attempted:
        # Must come first. Every branch below reads a counting field
        # (`candidates`, `scoped`, `excluded`, `lang`) off the trace, and on
        # this path all of them are placeholders -- so the second branch
        # matches unconditionally and reports a corpus-coverage gap for a
        # question the corpus answered. `ok=True` because nothing here failed:
        # a skipped stage must not become `diagnosis.blame`, which is what put
        # "Diagnose at: retrieval" underneath "Verdict: GROUNDED".
        return StageVerdict(
            stage="retrieval",
            ok=True,
            code="not-attempted",
            detail=(
                "Retrieval did not run. The question bound a structured-table "
                "query, so the count tool answered from the table directly and "
                "no passage was scored. retrieval.threshold did not apply to "
                "this answer, and nothing here indicates a corpus gap."
            ),
        )
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
    if not trace.candidates and trace.scoped == 0:
        if trace.jurisdiction is not None:
            # Must be tested before the language branch, not after. Both
            # branches are reached with `scoped == 0`, and the language
            # wording names a language and a count that are true of a
            # different filter -- so an empty *layer* was reported as "the
            # corpus holds nothing at all in 'en'" for a corpus with plenty
            # of English in it, which is a coverage gap that does not exist.
            unlabelled = (
                f" {trace.unlabelled} of them declare no jurisdiction at all."
                if trace.unlabelled
                else ""
            )
            return StageVerdict(
                stage="retrieval",
                ok=False,
                code="no-passages-in-jurisdiction",
                detail=(
                    f"No passage in this corpus is labelled "
                    f"{trace.jurisdiction!r}; all {trace.excluded} were excluded "
                    f"before scoring.{unlabelled} This layer is empty, which is "
                    f"not the same as the corpus being silent on the subject: a "
                    f"wider layer may still answer it."
                ),
            )
        return StageVerdict(
            stage="retrieval",
            ok=False,
            code="no-passages-in-language",
            detail=(
                f"The corpus holds nothing at all in {trace.lang!r}; all "
                f"{trace.excluded} passages were excluded before scoring. This is a "
                "corpus coverage gap, not a ranking problem."
            ),
        )
    if not trace.candidates:
        scope = (
            f"None of the {trace.scoped} passages in {trace.lang!r}"
            if trace.lang
            else "No passage in the index"
        )
        return StageVerdict(
            stage="retrieval",
            ok=False,
            code="no-lexical-overlap",
            detail=(
                f"{scope} shares a single scoring term with this question, so "
                "nothing was even scored. Either the corpus does not cover the "
                "subject, or the question's vocabulary does not match the corpus's."
            ),
        )
    best = trace.candidates[0]
    detail = (
        f"{len(trace.candidates)} candidates were scored and none cleared the "
        f"{_fmt(trace.threshold)} threshold. The best, {best.passage.passage_id}, "
        f"scored {_fmt(best.score)} and was short by "
        f"{_fmt(trace.threshold - best.score)} on "
        f"{len(best.matched)} of {len(trace.scoring_terms)} question terms "
        f"({', '.join(best.matched)})."
    )
    if trace.unmatched:
        detail += (
            f" No passage searched contained {', '.join(trace.unmatched)} — that part "
            "of the question is a corpus coverage gap, not a threshold setting."
        )
    return StageVerdict(stage="retrieval", ok=False, code="below-threshold", detail=detail)


def refusal_reason(trace: RetrievalTrace) -> str:
    """The stage-1 diagnosis code for a refusal — nothing else about it.

    For `cairn/refusal_stats.py`, which aggregates refusal reasons and must
    never hold anything drawn from the question itself. `_retrieval_verdict`
    computes a `.detail` string that quotes matched/unmatched question terms;
    this returns only `.code` — one of `"no-matching-rows"`,
    `"no-passages-in-language"`, `"no-passages-in-jurisdiction"`,
    `"no-lexical-overlap"`, or `"below-threshold"` for a trace with no
    accepted candidates,
    machine-stable and question-content-free by construction, per this
    module's own docstring. Call this only when `trace.accepted` is empty; on
    an accepted trace it returns `"passages-accepted"`, which is not a
    refusal reason at all.

    A trace with `attempted=False` reaches a refusal by exactly one route:
    `cairn.engine._answer_from_tables` bound a count query and it matched
    zero rows. That is a distinct operator signal — the table was found and
    read, and the value asked about is outside the data — so it gets its own
    code rather than borrowing `"no-passages-in-language"`, which claims a
    coverage gap that is not there. `cairn/refusal_stats.py` carries the
    legend and `docs/refusal-analytics.md` the operator's reading of it.
    """
    if not trace.attempted:
        return "no-matching-rows"
    return _retrieval_verdict(trace).code


def _answer_verdict(
    trace: RetrievalTrace, answer: Answer, dropped: tuple[Candidate, ...]
) -> StageVerdict:
    if not trace.attempted:
        # `no-evidence` below says "the answer stage was handed no passages,
        # so it refused ... look upstream at retrieval", and renders as NOT
        # REACHED. On the tool path the answer stage was reached, needed no
        # passages, and produced the answer -- there is no upstream to look at.
        if answer.kind == "grounded":
            return StageVerdict(
                stage="answer",
                ok=True,
                code="composed-from-table",
                detail=(
                    f"Composed from {len(answer.sources)} table row(s), verbatim. "
                    "Every figure in the answer was read out of the cited rows, "
                    "not out of a retrieved passage."
                ),
            )
        return StageVerdict(
            stage="answer",
            ok=True,
            code="no-matching-rows",
            detail=(
                "The count bound a table and a column and matched no row, so "
                "there was nothing to report and the answer refused. The table "
                "was read successfully: this says the value asked about falls "
                "outside the data, not that the corpus is missing anything."
            ),
        )
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


def candidate_readability(
    candidate: Candidate, overrides: dict[str, str] | None = None
) -> Measurement:
    """The reading level of the text this candidate would be quoted from.

    Cairn quotes passages verbatim, so the reading level of an answer is the
    reading level of the passage that won. An operator diagnosing a bad answer
    can see the score that chose it; until now they could not see whether the
    thing it chose is written at a level the asker can read.

    A language with no formula in force comes back with `grade=None` and a
    reason, and every renderer below prints the reason. Running the English
    formula over Arabic would produce a number with the right shape and no
    referent, which is the failure this repository refuses everywhere else.
    """
    return measure(candidate.passage.text, candidate.passage.lang, overrides)


def _candidate_rows(
    trace: RetrievalTrace, readability_overrides: dict[str, str] | None = None
) -> list[str]:
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
        # The term evidence, not just the score: a passage that scored on one
        # weak word and a passage that scored on four strong ones are different
        # findings, and the number alone does not tell them apart.
        rows.append(
            f"          matched {len(candidate.matched)}/{len(trace.scoring_terms)}: "
            + ", ".join(candidate.matched)
        )
        reading = candidate_readability(candidate, readability_overrides)
        rows.append(f"          readability {reading.describe()}")
    return rows


def _term_lines(trace: RetrievalTrace) -> list[str]:
    """What the question's own words did. Printed once per attempt, because a
    language restriction changes which of them could have matched anything."""
    if not trace.query_terms:
        return []
    lines = [f"  question terms:      {', '.join(trace.query_terms)}"]
    if trace.unmatched:
        lines.append(f"  in no passage:       {', '.join(trace.unmatched)}")
    if trace.ignored:
        lines.append(f"  too common to score: {', '.join(trace.ignored)}")
    return lines


def _jurisdiction_lines(result: AskResult) -> list[str]:
    """The layer decision: what was asked about, and what answered.

    Printed only when a jurisdiction was in force. A deployment that does not
    use layers gets a report byte-identical to the one it got before layers
    existed, which is the same rule the rest of this feature follows.
    """
    if result.jurisdiction is None:
        return []
    lines = [f"Layer:     {result.jurisdiction} (jurisdiction.default or --jurisdiction)"]
    rungs = [a.jurisdiction for a in result.attempts if a.jurisdiction is not None]
    ordered = list(dict.fromkeys(rungs))
    if len(ordered) > 1:
        lines.append("           widened through: " + " -> ".join(ordered))
    if result.cross_jurisdiction:
        answered = ", ".join(
            sorted({j for j in result.source_jurisdictions if j is not None})
        )
        lines.append(
            f"           answered from {answered}, not {result.jurisdiction} "
            "(cross-jurisdiction fallback)"
        )
    return lines


def _language_lines(result: AskResult) -> list[str]:
    detection = result.detection
    lines = [f"Language:  {detection.lang} ({detection.basis})"]
    if detection.coverage:
        shares = ", ".join(f"{code} {score:.2f}" for code, score in detection.coverage)
        lines.append(f"           corpus vocabulary coverage: {shares}")
    if result.cross_language:
        cited = ", ".join(sorted({s.lang for s in result.answer.sources}))
        lines.append(
            f"           answered in {detection.lang} from {cited} sources "
            "(cross-language fallback)"
        )
    return lines


def _attempt_lines(
    result: AskResult, readability_overrides: dict[str, str] | None = None
) -> list[str]:
    lines: list[str] = []
    for number, attempt in enumerate(result.attempts, start=1):
        trace = attempt.trace
        scope = (
            f"restricted to {trace.lang!r}"
            if attempt.scope == "language"
            else "widened to every language"
        )
        if attempt.jurisdiction is not None:
            scope += f", layer {attempt.jurisdiction!r}"
        header = (
            f"Attempt {number} ({scope}): {trace.scoped} passages scored, "
            f"{trace.excluded} excluded, {len(trace.candidates)} candidates"
        )
        if trace.unlabelled:
            # Said out loud rather than folded into `excluded`: a passage in
            # no layer is an authoring gap, and one in another layer is not.
            header += f" ({trace.unlabelled} declaring no jurisdiction)"
        lines.append(header)
        lines.extend(_term_lines(trace))
        lines.extend(_candidate_rows(trace, readability_overrides))
        lines.append("")
    return lines


def _margin_line(trace: RetrievalTrace, margin_warn: float) -> str | None:
    """One line reporting how close the ranking was, or `None` when there is
    no winner or no runner-up to compare it to. See `RetrievalTrace.margin`.
    """
    if trace.margin is None:
        return None
    runner_up = trace.candidates[1]
    line = (
        f"Margin:    {_fmt(trace.margin)} "
        f"(next: {runner_up.passage.passage_id} at {_fmt(runner_up.score)})"
    )
    if trace.margin < margin_warn:
        line += f" — WARN: below retrieval.margin_warn ({_fmt(margin_warn)})"
    return line


def render(
    result: AskResult,
    diagnosis: Diagnosis,
    *,
    index_summary: str,
    margin_warn: float = 0.02,
    readability_overrides: dict[str, str] | None = None,
) -> str:
    """The operator's plain-text report. Written to stdout above the answer."""
    answer = result.answer
    trace = answer.trace
    lines = [
        "=== retrieval trace " + "=" * (REPORT_WIDTH - 20),
        f"Question:  {trace.query}",
        f"Index:     {index_summary}",
        f"Threshold: {_fmt(trace.threshold)} (retrieval.threshold)",
        *_language_lines(result),
        *_jurisdiction_lines(result),
        "",
        *_attempt_lines(result, readability_overrides),
    ]
    for step, verdict in enumerate(diagnosis.stages, start=1):
        if verdict.code == "no-evidence":
            status = "NOT REACHED"
        elif verdict.code == "not-attempted":
            # Not "OK". This stage did not run, and this repository's own
            # standard is that a check which could not run is not a check
            # that passed -- `ok=True` here means "not to blame", which is a
            # different claim from "passed" and must not print as one.
            status = "NOT RUN"
        else:
            status = "OK" if verdict.ok else "FAILED"
        lines.append(f"Stage {step} - {verdict.stage}: {status} ({verdict.code})")
        lines.append(
            textwrap.fill(
                verdict.detail, width=REPORT_WIDTH, initial_indent="  ", subsequent_indent="  "
            )
        )
    margin_line = _margin_line(trace, margin_warn)
    lines.append("")
    if margin_line:
        lines.append(margin_line)
        lines.append("")
    if diagnosis.grounded:
        lines.append(f"Verdict: GROUNDED - {len(answer.sources)} source(s) cited.")
    else:
        lines.append("Verdict: NOT GROUNDED - refusal, no sources.")
    if diagnosis.blame:
        lines.append(f"Diagnose at: {diagnosis.blame}.")
    lines.append("=" * REPORT_WIDTH)
    return "\n".join(lines)


def _readability_payload(measurement: Measurement) -> dict[str, Any]:
    """One candidate's reading level, with absence spelled as null.

    `reason` is non-empty exactly when `grade` is null, so a consumer never
    has to guess whether a missing grade means "unmeasurable" or "forgot to
    measure".
    """
    return {
        "grade": measurement.grade,
        "formula": measurement.formula or None,
        "reason": measurement.reason or None,
        "words": measurement.words,
        "sentences": measurement.sentences,
        "mean_sentence_length": measurement.mean_sentence_length,
    }


def trace_payload(
    trace: RetrievalTrace,
    *,
    margin_warn: float | None = None,
    readability_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Machine-readable candidate list for ``ask --explain --json``.

    ``margin_warn`` is optional so a caller with no configured threshold in
    hand still gets the raw margin value; passing it additionally sets
    ``margin_below_warn``, the same comparison the text report renders as a
    WARN line.
    """
    return {
        "threshold": trace.threshold,
        # The layer this pass searched, and how many passages were set aside
        # for declaring none. Null and zero respectively when the corpus is
        # not layered, which is the shape every existing consumer already
        # reads for a field it has not heard of.
        "jurisdiction": trace.jurisdiction,
        "unlabelled": trace.unlabelled,
        # So a JSON consumer can tell a skipped retrieval stage from an empty
        # one without re-deriving it from the emptiness of every other field.
        "attempted": trace.attempted,
        "margin": trace.margin,
        "margin_below_warn": (
            margin_warn is not None and trace.margin is not None and trace.margin < margin_warn
        ),
        "query_terms": list(trace.query_terms),
        "unmatched_terms": list(trace.unmatched),
        "ignored_terms": list(trace.ignored),
        "candidates": [
            {
                "rank": rank,
                "score": candidate.score,
                "accepted": candidate.accepted,
                "passage_id": candidate.passage.passage_id,
                "doc_id": candidate.passage.doc_id,
                "title": candidate.passage.title,
                "lang": candidate.passage.lang,
                "jurisdiction": candidate.passage.jurisdiction,
                "excerpt": excerpt(candidate.passage.text),
                "matched_terms": list(candidate.matched),
                # `grade` is null, never 0, where no formula is in force. A
                # consumer that sums or sorts these must be able to tell an
                # unmeasured passage from an easy one.
                "readability": _readability_payload(
                    candidate_readability(candidate, readability_overrides)
                ),
            }
            for rank, candidate in enumerate(trace.candidates, start=1)
        ],
    }
