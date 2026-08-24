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
   output at all. "All 13 suites passed" reads like coverage; it is coverage
   minus whatever somebody turned off, and the diff that turned it off is long
   since merged.

So this script is the ratchet and the inventory. It runs after the gate, reads
the report the gate just wrote, and fails on:

- any suite scoring below the committed baseline, by any amount;
- any suite scoring **above** it that the baseline has not caught up with;
- any suite whose floor was lowered since the baseline;
- any suite in the baseline that this run did not score at all;
- any suite disabled in `plumbline/target.toml` without a declared gap saying
  what is missing and where the fix belongs;
- any suite whose floor is not the pinned harness's own default and which does
  not say why;
- a run that compared against no baseline, or against a different one.

**Why a floor needs a reason, and why the reason is checked here.** Each suite
the harness ships names a default floor, chosen by whoever wrote the metric.
Cairn overrides six of them. Four are stricter and two are looser, and every
one of those is a defensible call — but an unexplained loosening is exactly
the shape a red gate takes on its way to green, and a rule written in a
comment is a rule nobody enforces. `plumbline/target.toml` was carrying five
undocumented overrides on 2026-08-15 and the write-up that found them said
five; there were six. So the rule moved out of the prose: a floor that differs
from the default must carry `floor_reason`, and this script decides what "the
default" is by reading it out of the pinned harness rather than out of a
number typed in Cairn's own config, which could be wrong in the same commit
that made it wrong. A pin bump that changes a default therefore reopens the
question at the next gate run, which is the point.

**Why an improvement fails too, which it did not used to.** The first version
of this guard printed a note on a score that rose: *the baseline is behind,
refresh it.* A note is not a mechanism. Leave it unactioned — and nothing made
anyone action it — and the recorded bar stays at the old number while the
system performs above it, so the whole distance between the two becomes
invisible decay: a later change can give back every point of the improvement
and this guard will call it unchanged.

The objection at the time was that failing on an improvement makes every
unrelated change a two-commit dance. It does not, and the reason is the
determinism this project already relies on everywhere else. Scores move only
when answers move. Answers are produced by `cairn record` from a committed
corpus and a committed question set, and CI already refuses any commit whose
recorded bundle differs from what the engine now produces. So a change that
moves a score is, necessarily, a change that had to touch the evidence in that
same commit — and refreshing the baseline is one more command in a commit that
was already regenerating things. A change that touches nothing moves nothing
and sees no finding.

What this does *not* do is adopt the better number by itself. Nothing here
ratchets in either direction: both a fall and a rise stop the build and ask a
person to put the new bar in a reviewed diff, with the reason in the commit
message. The asymmetry is gone; the deliberateness is not.

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
work: the point is not that scores may never move, it is that a move must be a
reviewed diff in a committed file rather than a number nobody looked at. The
regeneration command is printed with every finding.

Exit codes follow the harness's vocabulary so a build log reads consistently:

    0  every scored suite matches the committed baseline, every disabled suite
       declares its gap, and every non-default floor says why it is not the
       default
    1  findings: a score moved off the baseline in either direction, a gap is
       undeclared, or a floor was overridden silently
    4  the guard could not run (no report, no baseline, unreadable input, no
       resolved harness to read the default floors out of) — a check that
       could not run is not a check that passed
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_AUDITS = "plumbline/audits"
DEFAULT_BASELINE = "plumbline/baseline.json"
DEFAULT_TARGET = "plumbline/target.toml"
DEFAULT_PIN = "plumbline.pin"
DEFAULT_CACHE_ROOT = ".plumbline-cache"

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

# Cairn's own key again: the harness ignores it, and it is required on any
# suite whose floor is not the harness's default for that suite.
FLOOR_REASON_KEY = "floor_reason"


class GuardError(Exception):
    """The guard could not run. Exit 4, never a quiet pass."""


@dataclass(frozen=True)
class Finding:
    """One thing wrong. `blocking` findings fail the build; the rest are
    printed because a reader should see them, not because they are faults.

    `label` exists because two blocking findings can mean opposite things. A
    build stopped by a score that rose is not a build stopped by a regression,
    and a log that called both "REGRESSION" would teach a reader to skim past
    the word.
    """

    blocking: bool
    subject: str
    detail: str
    label: str = "REGRESSION"


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


def pinned_harness_src(pin_path: Path, cache_root: Path) -> Path:
    """Where ./plumbline-gate.sh put the harness this repository is pinned to.

    Derived from the pin rather than searched for, so this can only ever read
    the commit the gate verified. A cache directory holding several refs is
    normal on a laptop; picking one by mtime would be picking whichever
    harness ran last.
    """
    try:
        pin_text = pin_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuardError(f"cannot read the pin at {pin_path}: {exc}") from exc
    match = re.search(r"(?m)^\s*ref\s*=\s*([0-9a-f]{40})\s*$", pin_text)
    if not match:
        raise GuardError(f"{pin_path} does not name a 40-character commit in a 'ref =' line")
    return cache_root / match.group(1) / "src"


def harness_defaults(src_dir: Path) -> dict[str, float]:
    """Every suite the pinned harness ships, and the floor it chose for itself.

    Read out of the harness's source with :mod:`ast` — parsed, never imported
    and never executed. The harness is deliberately not a dependency of this
    project and importing it here to read two class attributes would make it
    one, in the script whose whole job is to be independent of what it checks.

    An empty result is an error, not an empty answer. "No suite declares a
    default" and "this is not a harness checkout" produce the same dictionary,
    and one of them would silently excuse every floor in the target config
    from having a reason — a rule that stops applying when its input goes
    missing is not a rule.
    """
    suites_dir = src_dir / "plumbline" / "suites"
    if not suites_dir.is_dir():
        raise GuardError(
            f"no resolved harness at {src_dir}. Run ./plumbline-gate.sh first: it "
            f"is the one thing in this repository that fetches the harness, and "
            f"this check reads the suite defaults out of the commit it verified."
        )
    defaults: dict[str, float] = {}
    for module in sorted(suites_dir.glob("*.py")):
        try:
            tree = ast.parse(module.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise GuardError(f"cannot parse the pinned harness at {module}: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            attrs: dict[str, object] = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                ):
                    attrs[stmt.targets[0].id] = stmt.value.value
            suite_id = attrs.get("id")
            floor = attrs.get("default_floor")
            if attrs.get("implemented") is False:
                # A documented skeleton. The harness refuses to enable one, so
                # requiring the target config to mention it would be requiring
                # a configuration error.
                continue
            if isinstance(suite_id, str) and suite_id and isinstance(floor, (int, float)):
                defaults[suite_id] = float(floor)
    if not defaults:
        raise GuardError(
            f"the harness at {src_dir} declares no suite default floors. Either it "
            f"is not a harness checkout or the attribute was renamed upstream; "
            f"either way every floor in the target config would go unchecked."
        )
    return defaults


def unmentioned_suites(target: dict, defaults: dict[str, float]) -> list[Finding]:
    """Suites the pinned harness implements that the target config never names.

    The third way to switch a check off, and the only one nothing caught.
    `enabled = false` needs a declared gap, and a suite that stops being scored
    is caught by the baseline comparison — but both of those read the universe
    of suites out of `plumbline/target.toml` and `plumbline/baseline.json`. A
    diff that deletes `[suites.privacy]` from the config *and* its entry from
    the baseline deletes it from the universe too: the gate reports "13 suites
    passed", every set comparison in this file is over the survivors, the
    tests over the committed artifacts compare those two files to each other
    and agree, and the PII check is gone with nothing in the repository saying
    so. The harness will not catch it either — its config loader only rejects
    suites it does not know, never suites the config forgot.

    So the universe comes from the harness. A suite it ships is either enabled
    here or disabled here with a declared gap; being absent is not an option,
    because absence is the shape "we quietly stopped checking that" takes.
    """
    named = set(target.get("suites", {}))
    findings = []
    for suite_id in sorted(set(defaults) - named):
        findings.append(
            Finding(
                blocking=True,
                subject=suite_id,
                detail=(
                    f"is implemented by the pinned harness and is not mentioned "
                    f"in the target config at all — not enabled, not disabled "
                    f"with a declared gap, absent. A suite deleted from this "
                    f"file and from the baseline in one commit stops being "
                    f"checked and stops being counted, and every other check "
                    f"here reads its list of suites out of those two files. Add "
                    f"[suites.{suite_id}], enabled or with a gap."
                ),
                label="MISSING",
            )
        )
    return findings


def floor_findings(
    target: dict, defaults: dict[str, float]
) -> tuple[list[dict], list[Finding]]:
    """Every floor that is not the harness's own, and whether it says why.

    The gate reports the floor it applied. It has nothing to say about who
    chose that number or against what, and a floor is the strictness of the
    check itself: lower it far enough and a suite passes whatever the system
    does. So an override is allowed and an unexplained override is not.
    """
    overrides: list[dict] = []
    findings: list[Finding] = []
    for suite_id, spec in sorted(target.get("suites", {}).items()):
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        if suite_id not in defaults:
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"is enabled here and the pinned harness ships no suite by "
                        f"that name, so there is no default to hold its floor "
                        f"against. Known suites: {', '.join(sorted(defaults))}."
                    ),
                    label="UNKNOWN",
                )
            )
            continue
        default = defaults[suite_id]
        floor = spec.get("floor", default)
        if not isinstance(floor, (int, float)) or isinstance(floor, bool):
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=f"floor is {floor!r}, which is not a number.",
                    label="UNDECLARED",
                )
            )
            continue
        reason = str(spec.get(FLOOR_REASON_KEY, "")).strip()
        if abs(float(floor) - default) <= TOLERANCE:
            if reason:
                findings.append(
                    Finding(
                        blocking=False,
                        subject=suite_id,
                        detail=(
                            f"floor {float(floor):.2f} is the harness default and "
                            f"still carries a {FLOOR_REASON_KEY}; the reason is "
                            f"stale and reads as an override that is not one."
                        ),
                        label="note",
                    )
                )
            continue
        direction = "stricter than" if float(floor) > default else "LOOSER than"
        if not reason:
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"floor {float(floor):.2f} is {direction} the pinned "
                        f"harness's default of {default:.2f}, with no "
                        f"{FLOOR_REASON_KEY} in [suites.{suite_id}]. A floor is how "
                        f"strict this gate is; moving one without saying why is "
                        f"indistinguishable from moving it to make a failure pass. "
                        f"Write the reason, or restore {default:.2f}."
                    ),
                    label="UNDECLARED",
                )
            )
            continue
        overrides.append(
            {
                "suite": suite_id,
                "floor": float(floor),
                "default": default,
                "direction": direction,
                "reason": reason,
            }
        )
    return overrides, findings


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
        if not isinstance(spec, dict):
            continue
        if spec.get("enabled", True):
            # A gap declaration left behind on a suite that is now on. It is
            # not merely stale: it is loaded. The requirement below is "a
            # disabled suite must declare a gap", so a suite that already
            # carries one can be switched off in a one-word diff and satisfy
            # the requirement on the way past, with a sentence written for a
            # gap that closed. `multilingual` carried exactly that from the
            # milestone in which it was disabled.
            left = [key for key in GAP_KEYS if str(spec.get(key, "")).strip()]
            if left:
                findings.append(
                    Finding(
                        blocking=True,
                        subject=suite_id,
                        detail=(
                            f"is enabled and still declares "
                            f"{' and '.join(left)}. A gap declaration on a "
                            f"running suite pre-satisfies the check that a "
                            f"disabled suite must explain itself, so the next "
                            f"person to write `enabled = false` gets a pass "
                            f"from a sentence about a gap that closed. Delete "
                            f"it; the history belongs in the comment above."
                        ),
                        label="STALE",
                    )
                )
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
                    label="UNDECLARED",
                )
            )
            continue
        gaps.append({"suite": suite_id, **{key: spec[key] for key in GAP_KEYS}})
    return gaps, findings


def regression_findings(report: dict, baseline: dict) -> list[Finding]:
    """Compare this run against the committed bar, in both directions.

    Every scored suite must match the baseline exactly. Falling below it is a
    regression; rising above it is an improvement the record has not caught up
    with, and appearing without being in it at all is a suite running with no
    bar under it. All three stop the build, because all three end with a number
    in a committed file that is not the number the system produces.
    """
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
                blocking=True,
                subject=suite_id,
                detail=(
                    f"scored {now[suite_id]['score']:.4f} and is not in the committed "
                    f"baseline, so it is running with no bar under it — it can decay "
                    f"to its floor unnoticed. Adopt it in the commit that switched it "
                    f"on."
                ),
                label="UNPINNED",
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
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"score rose {previous['score']:.4f} -> "
                        f"{current['score']:.4f} ({delta:+.4f}), and the committed "
                        f"baseline still says {previous['score']:.4f}. Adopt it: an "
                        f"improvement nobody records is a bar nobody raised, and "
                        f"every point of it can be given back later without this "
                        f"check noticing."
                    ),
                    label="IMPROVEMENT",
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
        if current.get("n") != previous.get("n"):
            # A score is a fraction, and the baseline records both halves. A
            # suite that quietly stopped being able to check most of its
            # population reports a perfect score over what is left, and reads
            # exactly like a suite that checked everything. `passage_attribution`
            # is the live example: it scores only the items where a wrong
            # paragraph was available to answer from, so its denominator is a
            # property of the target's own retrieval and can collapse without
            # a single answer getting worse.
            fewer = (current.get("n") or 0) < (previous.get("n") or 0)
            findings.append(
                Finding(
                    blocking=True,
                    subject=suite_id,
                    detail=(
                        f"scored {current.get('n')} items, and the baseline "
                        f"recorded {previous.get('n')}. "
                        + (
                            "A score over a smaller population is a smaller "
                            "claim, whatever the number says."
                            if fewer else
                            "More is checked than the record admits; adopt it, "
                            "or the extra coverage can be lost later without "
                            "this check noticing."
                        )
                    ),
                    label="COVERAGE",
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


def uncovered(report: dict) -> list[str]:
    """Per suite: how much of its own population it could not check.

    A declared gap is a suite that did not run. This is the quieter cousin —
    a suite that ran and scored a fraction of what it was handed. The harness
    reports it per suite; the guard repeats it beside the verdict so that
    "13 suites passed" is never read as "everything was checked".

    An empty result is reported by the callers as a sentence rather than as
    nothing on the page. This reads one key out of somebody else's report
    format, and a pin bump that renamed it would turn every coverage line off
    at once — which, printed as an absence, is indistinguishable from a run in
    which every suite really did score everything.
    """
    lines = []
    for suite in report.get("suites", []):
        block = (suite.get("details") or {}).get("unverifiable") or {}
        if not block.get("count"):
            continue
        reasons = ", ".join(
            f"{reason} {len(ids)}" for reason, ids in sorted(block["reasons"].items())
        )
        lines.append(
            f"  {suite['suite']}: scored {block['scored']} of {block['eligible']} "
            f"eligible ({reasons}); unverifiable items are excluded, never passed"
        )
    return lines


def _render_gaps_terminal(gaps: list[dict]) -> list[str]:
    if gaps:
        plural = "" if len(gaps) == 1 else "s"
        lines = [f"declared gaps ({len(gaps)} suite{plural} not scored at all):"]
        for gap in gaps:
            lines.append(f"  {gap['suite']}: {gap['gap']}")
            lines.append(f"    the fix belongs in: {gap['fix_belongs_in']}")
        return lines
    return ["declared gaps: none — every implemented suite is enabled."]


def _render_overrides_terminal(overrides: list[dict]) -> list[str]:
    if overrides:
        plural = "" if len(overrides) == 1 else "s"
        lines = [
            f"floors that are not the harness's own ({len(overrides)} suite{plural}, "
            f"each with a recorded reason):"
        ]
        for entry in overrides:
            lines.append(
                f"  {entry['suite']}: {entry['floor']:.2f}, {entry['direction']} "
                f"the default {entry['default']:.2f}"
            )
        return lines
    # Said out loud, for the same reason the coverage line is: an absence
    # here and a check that stopped reading the harness print identically.
    return [
        "every floor is the pinned harness's own default — none was overridden."
    ]


def _render_findings_terminal(findings: list[Finding]) -> list[str]:
    if findings:
        return [
            f"{finding.label if finding.blocking else 'note':<11} "
            f"{finding.subject}: {finding.detail}"
            for finding in findings
        ]
    return ["no suite moved against the committed baseline."]


def render_terminal(
    *, report_path: Path, report: dict, baseline: dict, gaps: list[dict],
    findings: list[Finding], overrides: list[dict] = (),
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
    lines.extend(_render_gaps_terminal(gaps))
    lines.extend(_render_overrides_terminal(overrides))
    partial = uncovered(report)
    if partial:
        lines.append("suites that could not check everything they were handed:")
        lines += partial
    else:
        # Said out loud rather than left as an absence. "No coverage lines"
        # and "the harness stopped reporting coverage" print identically
        # otherwise, and one of those is a claim while the other is silence.
        lines.append(
            "every suite scored everything it was handed — no suite reported "
            "holding items out."
        )
    lines.extend(_render_findings_terminal(findings))
    if blocking:
        lines.append("")
        lines.append("If a finding above is intended, " + REGENERATE)
        lines.append(
            "An IMPROVEMENT is intended more often than not, and adopting it is "
            "the same command as accepting a fall: the point is that the bar "
            "moves in a reviewed diff, not that it may only move down."
        )
    lines.append(f"report: {report_path}")
    lines.append(f"GUARD: {verdict}")
    return lines


def render_markdown(
    *, report: dict, gaps: list[dict], findings: list[Finding],
    overrides: list[dict] = (),
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
    if overrides:
        lines += ["| Floor not the harness's own | Set to | Default | Why |",
                  "|---|---|---|---|"]
        for entry in overrides:
            lines.append(
                f"| `{entry['suite']}` | {entry['floor']:.2f} | "
                f"{entry['default']:.2f} | {entry['reason']} |"
            )
        lines.append("")
    else:
        lines += ["Every floor is the pinned harness's own default.", ""]
    partial = uncovered(report)
    if partial:
        lines += ["Suites that could not check everything they were handed:", ""]
        lines += [line.strip() and f"- {line.strip()}" for line in partial]
        lines.append("")
    else:
        lines += ["Every suite scored everything it was handed.", ""]
    if findings:
        lines += ["| | Suite | Finding |", "|---|---|---|"]
        for finding in findings:
            mark = f"**{finding.label.lower()}**" if finding.blocking else "note"
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
    parser.add_argument("--pin", default=DEFAULT_PIN,
                        help=f"the harness pin, read for its ref (default: {DEFAULT_PIN})")
    parser.add_argument("--cache", default=DEFAULT_CACHE_ROOT,
                        help=(f"where ./plumbline-gate.sh resolved the harness "
                              f"(default: {DEFAULT_CACHE_ROOT})"))
    parser.add_argument("--harness-src",
                        help="the harness src/ directory, bypassing --pin and --cache")
    parser.add_argument("--summary-file",
                        help="append the findings as markdown to this file")
    args = parser.parse_args(argv)

    try:
        report_path = Path(args.report) if args.report else newest_report(Path(args.audits))
        report = load_json(report_path, "audit report")
        baseline = load_json(Path(args.baseline), "committed baseline")
        target = load_target(Path(args.target))
        src = (
            Path(args.harness_src) if args.harness_src
            else pinned_harness_src(Path(args.pin), Path(args.cache))
        )
        defaults = harness_defaults(src)
        overrides, floor_faults = floor_findings(target, defaults)
        gaps, findings = assess(report, baseline, target)
        findings = unmentioned_suites(target, defaults) + floor_faults + findings
    except GuardError as exc:
        print(f"GUARD: COULD NOT RUN — {exc}", file=sys.stderr)
        print("GUARD: a check that could not run is not a check that passed.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    lines = render_terminal(
        report_path=report_path, report=report, baseline=baseline,
        gaps=gaps, findings=findings, overrides=overrides,
    )
    print("\n".join(lines))
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(render_markdown(
                report=report, gaps=gaps, findings=findings,
                overrides=overrides)) + "\n")
    return EXIT_FINDINGS if any(f.blocking for f in findings) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
