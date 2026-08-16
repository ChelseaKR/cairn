#!/usr/bin/env python3
"""The two checks Cairn adds on top of the pinned audit, and why they are here.

`./plumbline-gate.sh` answers one question: is every enabled suite above its
floor right now? That is necessary and it is not sufficient. Two things can be
true at once with a green gate:

1. **Scores decayed without breaching a floor.** `accuracy` can fall from 0.40
   to 0.36 above a floor of 0.35, or `refusal` from 1.00 to 0.91 above 0.90,
   and the gate is green both times. A floor is a minimum, not a ratchet. The
   pinned harness can compare a run against a committed baseline, and it does
   — but by design it *reports* what moved rather than failing, and it refuses
   to subtract scores at all once the evidence hash changes, which for Cairn
   is exactly the case that matters (a behavior change re-records the bundle,
   so every real regression arrives with a new dataset hash).
2. **A suite is switched off.** A disabled suite does not appear in the gate's
   output at all. "All 12 suites passed" reads like coverage; it is coverage
   minus whatever somebody turned off, and the diff that turned it off is long
   since merged.

So this script is the ratchet and the inventory. It runs after the gate, reads
the report the gate just wrote, and fails on:

- any suite scoring below the committed baseline, by any amount;
- any suite whose floor was lowered since the baseline;
- any suite in the baseline that this run did not score at all;
- any suite disabled in `plumbline/target.toml` without a declared gap saying
  what is missing and where the fix belongs;
- a run that compared against no baseline, or against a different one.

**Why Cairn subtracts scores the harness will not.** The harness refuses a
numeric comparison across a changed dataset hash, and it is right to: for a
general consumer, different evidence means the two numbers were never
measuring the same thing. Cairn's evidence is not authored, it is *derived* —
`plumbline/questions.toml` holds the authored questions and `cairn record`
produces every response from the running engine. When the bundle hash moves,
what moved is almost always the answers, and "did our answers get worse on the
same questions" is precisely the question a merge gate should be asking. So
Cairn makes the comparison the harness declines to make, on evidence Cairn
produced, and says so out loud rather than pretending the harness did it.

**Why any drop fails, however small.** The harness qualifies a move against a
suite's minimum detectable effect, because with 26 items a two-point wobble
does not generalize. That is the right caution for a claim about a population.
This is not that claim. The engine and the harness are both deterministic and
the evidence is committed, so a score that moved, moved because the system
changed. The finding is "this fixed set of answers got worse", which is worth
blocking a merge over at any size.

**The escape hatch, and why it is not a hole.** Regenerating the baseline
makes any of this green. That is deliberate and it is the only way it could
work: the point is not that scores may never fall, it is that a fall must be a
reviewed diff in a committed file rather than a number nobody looked at. The
regeneration command is printed with every finding.

Exit codes follow the harness's vocabulary so a build log reads consistently:

    0  no regression, and every disabled suite declares its gap
    1  findings: something got worse, or a gap is undeclared
    4  the guard could not run (no report, no baseline, unreadable input) —
       a check that could not run is not a check that passed
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_AUDITS = "plumbline/audits"
DEFAULT_BASELINE = "plumbline/baseline.json"
DEFAULT_TARGET = "plumbline/target.toml"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 4

# Scores are read from JSON written by a deterministic harness, so an
# unchanged run reproduces them exactly. The tolerance exists only so that a
# float round-trip can never invent a finding.
TOLERANCE = 1e-9

REGENERATE = (
    "regenerate deliberately, in the commit that changes the behavior:\n"
    "    python3 -m cairn index && python3 -m cairn record\n"
    "    PYTHONPATH=.plumbline-cache/<pinned-ref>/src python3 -m plumbline \\\n"
    "        audit --config plumbline/target.toml --out plumbline/audits\n"
    "    PYTHONPATH=.plumbline-cache/<pinned-ref>/src python3 -m plumbline \\\n"
    "        baseline --from plumbline/audits/<run-id>/report.json \\\n"
    "        --out plumbline/baseline.json\n"
    "`audit` rather than the gate, because the gate loads the baseline you are\n"
    "about to replace and will refuse if it cannot — which is the right\n"
    "behaviour and the wrong step to be stuck on."
)

# Keys Cairn requires on a disabled suite. The harness never reads a disabled
# suite's table, so these are Cairn's own and cost the harness nothing.
GAP_KEYS = ("gap", "fix_belongs_in")


class GuardError(Exception):
    """The guard could not run. Exit 4, never a quiet pass."""


@dataclass(frozen=True)
class Finding:
    """One thing wrong. `blocking` findings fail the build; the rest are
    printed because a reader should see them, not because they are faults."""

    blocking: bool
    subject: str
    detail: str


def load_json(path: Path, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise GuardError(f"no {what} at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"unreadable {what} at {path}: {exc}") from exc


def load_target(path: Path) -> dict:
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise GuardError(f"no target configuration at {path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GuardError(f"unreadable target configuration at {path}: {exc}") from exc


def newest_report(audits_dir: Path) -> Path:
    """The report the gate wrote most recently.

    The audit directory is generated state, not tracked, so in CI there is
    exactly one. Locally there may be several from earlier runs and the newest
    is the one that just ran. `--report` names one outright when that guess is
    not good enough.
    """
    reports = sorted(audits_dir.glob("*/report.json"), key=lambda p: p.stat().st_mtime)
    if not reports:
        raise GuardError(
            f"no audit report under {audits_dir}. Run ./plumbline-gate.sh first: "
            f"this checks the report the gate produces, it does not produce one."
        )
    return reports[-1]


def declared_gaps(target: dict) -> tuple[list[dict], list[Finding]]:
    """Every suite switched off in the target config, with its declaration.

    A suite may be disabled — some gaps are real and the honest move is to say
    so. What it may not be is disabled silently, because the gate's output
    lists what ran and nothing at all about what did not.
    """
    gaps: list[dict] = []
    findings: list[Finding] = []
    for suite_id, spec in sorted(target.get("suites", {}).items()):
        if not isinstance(spec, dict) or spec.get("enabled", True):
            continue
        missing = [key for key in GAP_KEYS if not str(spec.get(key, "")).strip()]
        if missing:
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"disabled with no {' and no '.join(missing)} declared. A "
                        f"suite that is off is a claim nobody is checking; say in "
                        f"[suites.{suite_id}] what is missing (gap) and where the "
                        f"fix belongs (fix_belongs_in)."
                    ),
                )
            )
            continue
        gaps.append({"suite": suite_id, **{key: spec[key] for key in GAP_KEYS}})
    return gaps, findings


def regression_findings(report: dict, baseline: dict) -> list[Finding]:
    """Compare this run against the committed bar."""
    findings: list[Finding] = []

    comparison = report.get("baseline")
    if not comparison:
        return [
            Finding(
                blocking=True,
                subject="baseline",
                detail=(
                    "this run compared against no baseline at all, so nothing "
                    "would have noticed a score falling. Set `baseline = "
                    f"{DEFAULT_BASELINE}` in plumbline.pin."
                ),
            )
        ]

    against = comparison.get("against", {})
    if against.get("source_run_id") != baseline.get("source_run_id"):
        findings.append(
            Finding(
                blocking=True,
                subject="baseline",
                detail=(
                    f"the run compared against baseline "
                    f"{against.get('source_run_id')!r}, but the committed "
                    f"baseline is {baseline.get('source_run_id')!r}. The gate and "
                    f"this check must be holding the same bar."
                ),
            )
        )

    now = {suite["suite"]: suite for suite in report.get("suites", [])}
    before = {suite["suite"]: suite for suite in baseline.get("suites", [])}

    for suite_id in sorted(set(before) - set(now)):
        findings.append(
            Finding(
                blocking=True,
                subject=suite_id,
                detail=(
                    f"scored {before[suite_id]['score']:.4f} in the baseline and was "
                    f"not scored at all in this run. A suite that stopped running is "
                    f"a check that stopped checking."
                ),
            )
        )

    for suite_id in sorted(set(now) - set(before)):
        findings.append(
            Finding(
                blocking=False,
                subject=suite_id,
                detail=(
                    f"scored {now[suite_id]['score']:.4f}; it is not in the baseline, "
                    f"so there is nothing to compare it against yet."
                ),
            )
        )

    for suite_id in sorted(set(now) & set(before)):
        current, previous = now[suite_id], before[suite_id]
        delta = current["score"] - previous["score"]
        if delta < -TOLERANCE:
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"score fell {previous['score']:.4f} -> "
                        f"{current['score']:.4f} ({delta:+.4f}), above its floor of "
                        f"{current['floor']:.2f}. A floor is a minimum, not a bar "
                        f"the score is allowed to drift down to."
                    ),
                )
            )
        elif delta > TOLERANCE:
            findings.append(
                Finding(
                    blocking=False,
                    subject=suite_id,
                    detail=(
                        f"score rose {previous['score']:.4f} -> "
                        f"{current['score']:.4f} ({delta:+.4f}). The baseline is "
                        f"behind: refresh it to make the improvement the new bar."
                    ),
                )
            )
        if current["floor"] < previous["floor"] - TOLERANCE:
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"floor lowered {previous['floor']:.2f} -> "
                        f"{current['floor']:.2f}. Moving the bar down is how a red "
                        f"gate becomes green without anything being fixed."
                    ),
                )
            )
        if previous["verdict"] == "PASS" and current["verdict"] != "PASS":
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=f"{previous['verdict']} -> {current['verdict']} since the baseline.",
                )
            )
    return findings


def assess(report: dict, baseline: dict, target: dict) -> tuple[list[dict], list[Finding]]:
    gaps, gap_findings = declared_gaps(target)
    return gaps, gap_findings + regression_findings(report, baseline)


def render_terminal(
    *, report_path: Path, report: dict, baseline: dict, gaps: list[dict],
    findings: list[Finding],
) -> list[str]:
    blocking = [f for f in findings if f.blocking]
    verdict = "FAIL" if blocking else "PASS"
    against = (report.get("baseline") or {}).get("against", {})
    lines = [
        f"GUARD: {verdict} — {report.get('target')}, run "
        f"{report.get('provenance', {}).get('run_id')}, against baseline "
        f"{against.get('source_run_id', baseline.get('source_run_id'))}"
    ]
    comparison = report.get("baseline")
    if comparison:
        lines.append(f"harness comparison: {comparison.get('summary')}")
        for reason in comparison.get("refusals", []):
            lines.append(f"  harness refused a numeric comparison: {reason}")
            lines.append("  this check makes it anyway; see audit_guard.py for why.")
    if gaps:
        plural = "" if len(gaps) == 1 else "s"
        lines.append(f"declared gaps ({len(gaps)} suite{plural} not scored at all):")
        for gap in gaps:
            lines.append(f"  {gap['suite']}: {gap['gap']}")
            lines.append(f"    the fix belongs in: {gap['fix_belongs_in']}")
    else:
        lines.append("declared gaps: none — every implemented suite is enabled.")
    if findings:
        for finding in findings:
            mark = "REGRESSION" if finding.blocking else "note      "
            lines.append(f"{mark} {finding.subject}: {finding.detail}")
    else:
        lines.append("no suite moved against the committed baseline.")
    if blocking:
        lines.append("")
        lines.append("If a finding above is intended, " + REGENERATE)
    lines.append(f"report: {report_path}")
    lines.append(f"GUARD: {verdict}")
    return lines


def render_markdown(
    *, report: dict, gaps: list[dict], findings: list[Finding]
) -> list[str]:
    blocking = [f for f in findings if f.blocking]
    lines = [
        "",
        "## Cairn audit guard",
        "",
        f"**{'FAIL' if blocking else 'PASS'}** — regression against the committed "
        f"baseline, and the inventory of what was not scored.",
        "",
    ]
    if gaps:
        lines += ["| Suite not scored | What is missing | Where the fix belongs |",
                  "|---|---|---|"]
        for gap in gaps:
            lines.append(f"| `{gap['suite']}` | {gap['gap']} | {gap['fix_belongs_in']} |")
        lines.append("")
    else:
        lines += ["Every implemented suite is enabled.", ""]
    if findings:
        lines += ["| | Suite | Finding |", "|---|---|---|"]
        for finding in findings:
            mark = "**regression**" if finding.blocking else "note"
            lines.append(f"| {mark} | `{finding.subject}` | {finding.detail} |")
        lines.append("")
    else:
        lines += ["No suite moved against the committed baseline.", ""]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_guard.py",
        description=(
            "Fail on an audit score that fell below the committed baseline, or a "
            "suite disabled without a declared gap. Run after ./plumbline-gate.sh."
        ),
    )
    parser.add_argument("--report", help="report.json to check (default: the newest)")
    parser.add_argument("--audits", default=DEFAULT_AUDITS,
                        help=f"where the gate writes reports (default: {DEFAULT_AUDITS})")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE,
                        help=f"the committed bar (default: {DEFAULT_BASELINE})")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"the audit target config (default: {DEFAULT_TARGET})")
    parser.add_argument("--summary-file",
                        help="append the findings as markdown to this file")
    args = parser.parse_args(argv)

    try:
        report_path = Path(args.report) if args.report else newest_report(Path(args.audits))
        report = load_json(report_path, "audit report")
        baseline = load_json(Path(args.baseline), "committed baseline")
        target = load_target(Path(args.target))
        gaps, findings = assess(report, baseline, target)
    except GuardError as exc:
        print(f"GUARD: COULD NOT RUN — {exc}", file=sys.stderr)
        print("GUARD: a check that could not run is not a check that passed.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    lines = render_terminal(
        report_path=report_path, report=report, baseline=baseline,
        gaps=gaps, findings=findings,
    )
    print("\n".join(lines))
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(render_markdown(
                report=report, gaps=gaps, findings=findings)) + "\n")
    return EXIT_FINDINGS if any(f.blocking for f in findings) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
