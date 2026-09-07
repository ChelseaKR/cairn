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

Probes may carry a `lang` and a `jurisdiction`, and where they do, each slice
gets its own band. One threshold for four languages either over-refuses in
the narrow band or over-answers in the wide one, and a set mixing them can
report NO SEPARATING THRESHOLD overall while every language separates
cleanly on its own — which is a recommendation, not a dead end, and the
overall number hides it.

This is advisory, like `cairn lint` and `cairn diff`: it never edits
`cairn.toml`, and choosing a new threshold is the operator's decision, not
this tool's. `--emit-config` writes the tables to stdout for an operator to
read, edit and paste; it applies nothing. What this changes is whether that
decision is informed by a number measured against their own corpus, or by
nothing.
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
    # The language this probe was *answered in* and the layer it was
    # *asked about*, after the probe's own labels and the configuration's
    # defaults have both been resolved — not the raw strings in the file.
    #
    # The distinction decides what `--emit-config` can recommend. The bundled
    # example probe set labels its Spanish and Arabic probes and leaves the
    # English ones to detection, exactly as `cairn ask` does; grouping on the
    # authored field put four English probes in no slice at all and emitted a
    # `[retrieval.threshold_by_language]` table with no `en` in it. A
    # recommendation silently missing the language most of the set is written
    # in is worse than no recommendation.
    #
    # `jurisdiction` is `None` for an unlayered corpus, where it is genuinely
    # absent rather than merely unwritten.
    lang: str | None
    jurisdiction: str | None
    # The threshold this probe was actually gated at, and the key it came
    # from. Recorded per probe rather than read off the report, because with
    # override tables in play the probes in one set are not all gated at the
    # same number, and a report that printed one would be printing a number
    # that decided some of its own rows and not others.
    threshold: float
    threshold_key: str
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
    def tool_probes(self) -> tuple[ProbeResult, ...]:
        """Probes answered without retrieval — reported, never averaged.

        A probe the count tool handled never reached `retrieval.threshold`,
        so putting it in the band arithmetic below asks which threshold would
        have classified a probe that no threshold classified.
        """
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

    def slice(self, results: tuple[ProbeResult, ...]) -> CalibrationReport:
        """A sub-report over a subset of these probes.

        Every band property above is a pure function of `results`, so a slice
        is the same type rather than a parallel one — there is no second
        implementation of "worst answer probe" to disagree with the first.
        """
        return CalibrationReport(threshold=self.threshold, results=results)

    def by_label(self, key: str) -> dict[str, CalibrationReport]:
        """Sub-reports grouped by a probe label, for labelled probes only.

        A probe that does not carry the label is left out rather than
        collected under a placeholder: "the probes that did not say" is not a
        language and not a layer, and a band computed over it would be
        reported beside the real ones as though it were.
        """
        groups: dict[str, list[ProbeResult]] = {}
        for result in self.results:
            value = getattr(result, key)
            if value is not None:
                groups.setdefault(value, []).append(result)
        return {
            value: self.slice(tuple(members))
            for value, members in sorted(groups.items())
        }

    @property
    def thresholds_in_force(self) -> tuple[str, ...]:
        """The distinct config keys that gated these probes, sorted.

        More than one means this report's own `threshold` is not the number
        that decided every row in it, which the renderer says out loud rather
        than printing a single figure over a mixed set.
        """
        return tuple(sorted({r.threshold_key for r in self.results}))

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
        for label in ("lang", "jurisdiction"):
            if label in probe and not isinstance(probe[label], str):
                raise CalibrationError(
                    f"{file}: probe {probe['question']!r} has a non-string "
                    f"{label!r}"
                )
    return probes


def calibrate(index: Index, cfg: Config, probes_path: str | Path) -> CalibrationReport:
    results = []
    for probe in load_probes(probes_path):
        lang = probe.get("lang")
        jurisdiction = probe.get("jurisdiction")
        result = ask(
            probe["question"], index, cfg, lang=lang, jurisdiction=jurisdiction
        )
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
                lang=result.answer.lang,
                jurisdiction=result.jurisdiction,
                threshold=trace.threshold,
                threshold_key=trace.threshold_key,
                top_score=top_score,
                outcome=outcome,
                correct=(outcome == probe["behavior"]),
            )
        )
    return CalibrationReport(threshold=cfg.threshold, results=tuple(results))


def _header(report: CalibrationReport) -> str:
    """The first line: how many probes, gated by what.

    Not one threshold with a footnote. With override tables in play the probes
    in one set are gated at several different numbers, and a single figure
    here would be the number that decided some of these rows and not others.
    """
    in_force = report.thresholds_in_force
    if len(in_force) > 1:
        return (
            f"{len(report.results)} probe(s), gated by {len(in_force)} different "
            f"keys: {', '.join(in_force)}"
        )
    return f"{len(report.results)} probe(s) against threshold {report.threshold:.3f}"


def _band_line(report: CalibrationReport) -> str:
    """One slice's verdict in one line: the band, or why there is none."""
    worst, best = report.worst_answer_score, report.best_refuse_score
    gap = report.gap
    if gap is None:
        missing = "no 'answer' probes" if worst is None else "no 'refuse' probes"
        return f"no band ({missing} that retrieval scored)"
    assert worst is not None and best is not None
    if gap <= 0:
        return (
            f"NO SEPARATING THRESHOLD (worst answer {worst:.3f} <= "
            f"best refuse {best:.3f})"
        )
    suggested = report.suggested_threshold
    assert suggested is not None
    return (
        f"band {best:.3f}..{worst:.3f}  gap {gap:.3f}  midpoint {suggested:.3f}"
    )


def _slice_lines(report: CalibrationReport, key: str, heading: str) -> list[str]:
    """Per-slice bands for one probe label, or nothing when none carry it."""
    groups = report.by_label(key)
    if not groups:
        return []
    lines = ["", f"By {heading}:"]
    for value, group in groups.items():
        in_force = group.thresholds_in_force
        gate = in_force[0] if len(in_force) == 1 else f"{len(in_force)} different keys"
        lines.append(
            f"  {value:<16} n={len(group.results):<3} {_band_line(group)}  "
            f"[gated by {gate}]"
        )
    unlabelled = sum(1 for r in report.results if getattr(r, key) is None)
    if unlabelled:
        lines.append(
            f"  ({unlabelled} probe(s) carry no {key}, and are in none of the "
            f"bands above)"
        )
    return lines


def emit_config(report: CalibrationReport) -> str:
    """The override tables this measurement recommends, as TOML on stdout.

    Never applied and never written to a file: adopting a threshold is the
    operator's decision, exactly as it is for the single one, and a tool that
    edited `cairn.toml` would be making that decision by being run.

    A slice that does not separate is emitted as a comment naming the two
    scores rather than omitted. Omitting it would leave the operator reading a
    table that silently covers three of their four languages, and the missing
    one is the one that needs them.
    """
    lines = [
        "# Recommended by `cairn calibrate --emit-config`. Nothing has been",
        "# applied: paste what you agree with into cairn.toml.",
        "#",
        "# Each midpoint is the middle of that slice's own band — the same",
        "# reasoning DESIGN.md applies to the shipped default, measured per",
        "# slice instead of once over all of them.",
    ]
    for key, table in (
        ("lang", "threshold_by_language"),
        ("jurisdiction", "threshold_by_jurisdiction"),
    ):
        groups = report.by_label(key)
        if not groups:
            continue
        lines.append("")
        lines.append(f"[retrieval.{table}]")
        for value, group in groups.items():
            suggested = group.suggested_threshold
            if suggested is None:
                lines.append(
                    f"# {value} = ?  # {_band_line(group)}; nothing to recommend"
                )
            else:
                lines.append(f'"{value}" = {suggested:.3f}')
    return "\n".join(lines)


def render(report: CalibrationReport) -> str:
    lines = [_header(report)]
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

    lines.extend(_slice_lines(report, "lang", "language"))
    lines.extend(_slice_lines(report, "jurisdiction", "jurisdiction"))

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
