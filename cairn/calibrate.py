"""Threshold recalibration against a real corpus.

DESIGN.md's own words, in the "Configuration" table's calibration note: the
relevance threshold is "set empirically against the demo corpus... re-check
it against probe questions when the corpus changes." That re-check has
existed only as a sentence an operator has to remember to act on by hand —
this is the tool that acts on it.

An operator supplies a probe file: real questions someone who has read the
corpus expects the system to answer, and real questions it should refuse.
Same shape as `tests/probes.py`'s IN_CORPUS/OFF_TOPIC split — the exact
measurement `retrieval.threshold`'s shipped default came from — but simpler:
no `answering_sources`, no `fact_id`, nothing audit-specific, because
picking a threshold needs only two facts about each probe: what it is, and
whether the system should answer it.

This is advisory, like `cairn lint` and `cairn diff`: it never edits
`cairn.toml`, and choosing a new threshold is the operator's decision, not
this tool's. What it changes is whether that decision is informed by a
number measured against their own corpus, or by nothing.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.config import Config
from cairn.engine import ask
from cairn.index import Index

Behavior = str  # "answer" | "refuse"


class CalibrationError(ValueError):
    """The probe file is malformed."""


@dataclass(frozen=True)
class ProbeResult:
    question: str
    behavior: Behavior  # what the operator expects
    lang: str | None
    # The best-scoring candidate's score; 0.0 if scoring ran and nothing
    # scored. `None` when scoring was never consulted at all -- the
    # structured-table count tool answered (or refused) this probe before
    # retrieval ran, so there is no score to compare and no value of
    # retrieval.threshold that could have changed the outcome. Recording that
    # as 0.0 made a correctly-answered probe the worst 'answer' probe in the
    # set, drove `gap` negative, and withheld the recommendation the tool
    # exists to make (issue #91).
    top_score: float | None
    outcome: Behavior  # what actually happened at the configured threshold
    correct: bool


@dataclass(frozen=True)
class CalibrationReport:
    threshold: float
    results: tuple[ProbeResult, ...]

    @property
    def answer_probes(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.behavior == "answer")

    @property
    def refuse_probes(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.behavior == "refuse")

    @property
    def scored_probes(self) -> tuple[ProbeResult, ...]:
        """Probes a threshold could actually have decided.

        Excludes the tool-answered ones. A probe the count tool handled never
        reached `retrieval.threshold`, so including it in the band arithmetic
        below asks what threshold would have classified a probe no threshold
        classified.
        """
        return tuple(r for r in self.results if r.top_score is not None)

    @property
    def tool_probes(self) -> tuple[ProbeResult, ...]:
        """Probes answered without retrieval — reported, never averaged."""
        return tuple(r for r in self.results if r.top_score is None)

    @property
    def worst_answer_score(self) -> float | None:
        scores = [r.top_score for r in self.answer_probes if r.top_score is not None]
        return min(scores) if scores else None

    @property
    def best_refuse_score(self) -> float | None:
        scores = [r.top_score for r in self.refuse_probes if r.top_score is not None]
        return max(scores) if scores else None

    @property
    def gap(self) -> float | None:
        """The band a threshold has to sit inside to get every probe right.
        `None` when there is nothing to compare (need at least one probe of
        each kind); not-positive when no threshold value can separate them."""
        worst, best = self.worst_answer_score, self.best_refuse_score
        if worst is None or best is None:
            return None
        return worst - best

    @property
    def suggested_threshold(self) -> float | None:
        """The midpoint of the gap — the same reasoning DESIGN.md's own
        calibration note applies to the shipped default. `None` when there
        is no positive gap to sit inside."""
        gap = self.gap
        if gap is None or gap <= 0:
            return None
        worst, best = self.worst_answer_score, self.best_refuse_score
        assert worst is not None and best is not None  # gap positive implies both present
        return (worst + best) / 2

    @property
    def misclassified(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if not r.correct)

    @property
    def safe(self) -> bool:
        """The configured threshold gets every probe right. A `None` gap
        (nothing to compare) counts as unsafe: it means the probe set cannot
        actually vouch for the configured threshold either way."""
        return not self.misclassified and self.gap is not None


def load_probes(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        raise CalibrationError(f"no probe file at {file}")
    with open(file, "rb") as handle:
        data = tomllib.load(handle)
    probes: list[dict[str, Any]] = data.get("probe", [])
    if not probes:
        raise CalibrationError(f"{file}: no [[probe]] entries")
    for probe in probes:
        if not probe.get("question"):
            raise CalibrationError(f"{file}: a probe is missing 'question'")
        if probe.get("behavior") not in ("answer", "refuse"):
            raise CalibrationError(
                f"{file}: probe {probe['question']!r} has behavior "
                f"{probe.get('behavior')!r}; expected 'answer' or 'refuse'"
            )
        if "lang" in probe and not isinstance(probe["lang"], str):
            raise CalibrationError(
                f"{file}: probe {probe['question']!r} has a non-string 'lang'"
            )
    return probes


def calibrate(index: Index, cfg: Config, probes_path: str | Path) -> CalibrationReport:
    results = []
    for probe in load_probes(probes_path):
        lang = probe.get("lang")
        result = ask(probe["question"], index, cfg, lang=lang)
        trace = result.answer.trace
        if not trace.attempted:
            # Not 0.0. Retrieval never ran, so "the best candidate scored
            # zero" would be a measurement of something that did not happen.
            top_score: float | None = None
        else:
            top_score = trace.candidates[0].score if trace.candidates else 0.0
        outcome = "answer" if result.answer.kind == "grounded" else "refuse"
        results.append(
            ProbeResult(
                question=probe["question"],
                behavior=probe["behavior"],
                lang=lang,
                top_score=top_score,
                outcome=outcome,
                correct=(outcome == probe["behavior"]),
            )
        )
    return CalibrationReport(threshold=cfg.threshold, results=tuple(results))


def render(report: CalibrationReport) -> str:
    lines = [f"{len(report.results)} probe(s) against threshold {report.threshold:.3f}"]
    for r in report.results:
        mark = "ok" if r.correct else "MISCLASSIFIED"
        score = "  n/a" if r.top_score is None else f"{r.top_score:.3f}"
        lines.append(
            f"  {mark:14} expect={r.behavior:<6} got={r.outcome:<6} "
            f"score={score}  {r.question}"
        )
    lines.append("")
    if report.tool_probes:
        lines.append(
            f"{len(report.tool_probes)} probe(s) scored 'n/a': answered by the "
            "structured-table tool without retrieval, so no threshold applies to "
            "them and they are excluded from the band below."
        )
        lines.append("")

    worst, best = report.worst_answer_score, report.best_refuse_score
    if worst is None:
        lines.append("No 'answer' probes in this set.")
    else:
        lines.append(f"Worst 'answer' probe score:  {worst:.3f}")
    if best is None:
        lines.append("No 'refuse' probes in this set.")
    else:
        lines.append(f"Best 'refuse' probe score:   {best:.3f}")

    if report.gap is None:
        lines.append(
            "Cannot compute a threshold band: need at least one 'answer' probe and "
            "one 'refuse' probe that retrieval actually scored."
        )
    elif report.gap <= 0:
        lines.append(
            f"NO SEPARATING THRESHOLD: the worst 'answer' probe ({worst:.3f}) scores at "
            f"or below the best 'refuse' probe ({best:.3f}). No value of "
            f"retrieval.threshold gets every probe in this set right against this "
            f"corpus as it stands — widen the corpus, revise the probes, or accept "
            f"that something will misclassify."
        )
    else:
        lines.append(
            f"Gap: {report.gap:.3f}  Suggested threshold (midpoint): "
            f"{report.suggested_threshold:.3f}"
        )

    lines.append("")
    if report.safe:
        lines.append(
            f"Configured threshold {report.threshold:.3f} classifies every probe correctly."
        )
    elif not report.misclassified:
        # `safe` is False here only because there is no band to vouch with.
        # The old text said "misclassifies 0 of 4 probe(s):" and then listed
        # nothing, which reads as a failure that did not happen.
        lines.append(
            f"Configured threshold {report.threshold:.3f} classifies every probe "
            "correctly, but this probe set cannot vouch for it: there is no "
            "band to compare it against (see above)."
        )
    else:
        lines.append(
            f"Configured threshold {report.threshold:.3f} misclassifies "
            f"{len(report.misclassified)} of {len(report.results)} probe(s):"
        )
        for r in report.misclassified:
            detail = (
                "answered by the table tool, no score"
                if r.top_score is None
                else f"score {r.top_score:.3f}"
            )
            lines.append(
                f"  expected {r.behavior}, got {r.outcome} ({detail}): {r.question}"
            )
    return "\n".join(lines)
