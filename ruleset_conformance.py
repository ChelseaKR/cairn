"""Is the ruleset GitHub is enforcing the ruleset this repository committed?

`.github/workflows/ruleset-check.yml` used to ask a narrower question:

    active_count=$(gh api "repos/${REPO}/rulesets" --jq \\
      '[.[] | select(.enforcement == "active")] | length')

That counts rulesets. It says nothing about what any of them requires, which
branch it targets, or who may skip it -- so an active ruleset requiring no
checks at all, or one edited afterwards, satisfied it exactly the way the real
one does. `tests/test_rulesets.py` checks the committed file thoroughly and
`ruleset-check.yml` checked that *a* ruleset existed, and the step between them
-- that the live ruleset is the committed one -- was checked by nothing.

**It was not hypothetical.** On 2026-08-28 the enforced ruleset (id `21223426`)
carried

    "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole",
                       "bypass_mode": "always"}]

while `.github/rulesets/main.json` carried `"bypass_actors": []`, and nothing
compared the two.

**The enforced value is the correct one.** That actor is the repository
owner's standing bypass, kept deliberately and permanently: an agent once set
a ruleset that locked the owner out of their own repository, and restoring
access took a sweep across eighteen repositories. The owner's instruction
afterwards was that they must always be able to bypass, in any repository.
The committed file, and the prose and test that argued for an empty list, were
what needed correcting -- and this module was written pointing the wrong way
before that was known. Its first version would have failed forever against a
correct configuration, which is its own lesson: a conformance check inherits
whatever the committed expectation gets wrong.

So the bypass list is not compared by equality alone. Three things are checked
independently, because equality between two wrong values is the failure mode
that matters here:

1. `OWNER_BYPASS` must be **present in the enforced ruleset**. An empty list
   coming back from the API is the lockout incident recurring, and it must
   read as a failure however tidy the committed file looks.
2. `OWNER_BYPASS` must be **present in the committed ruleset**, so a future
   edit "restoring" the empty list is caught at the file rather than only
   after somebody reapplies it.
3. Any **other** bypass actor -- a team, a GitHub App, a second role -- is a
   finding in either direction. That is the threat actually worth guarding,
   and it is the one an equality check against a hand-edited file would let
   through the moment both sides were edited together.

This module is the missing comparison, and it is a module rather than four more
lines of `jq` so that it can be tested offline against fixtures -- including
both directions of the bypass rule, which `tests/test_rulesets.py` carries. It
performs no network access of its own: the caller hands it the live JSON, so
the thing that fetches and the thing that judges stay separable, the same split
`plumbline-gate.sh` and `audit_guard.py` already use.

**A field that is not there is not a field that is empty.** GitHub omits
`bypass_actors` from a ruleset payload unless the caller may see it, and the
first version of this module read the omission through `.get(...) or []` --
so an unreadable field and an emptied one produced the same sentence, and the
sentence said the lockout had happened.

That fired for real. Issue #80, opened by the weekly job on 2026-08-31,
reported the owner's bypass as NOT enforced against a ruleset that had carried
it since 2026-08-26 and had not been touched since; read with credentials that
can see the field, the same ruleset conforms. The report was the token's blind
spot wearing the incident's words.

It is the worst possible false positive, for two reasons. The remedy it points
at is "reapply the committed ruleset", and reapplying is how an owner gets
locked out. And it makes the one finding this check exists for unreadable:
once the alarm fires without a fire, nobody can tell the next one apart.

So the bypass rule now has three outcomes rather than two. Present and correct
is conformance; present and wrong is drift; **absent is neither** -- it raises
:class:`CannotJudge`, and the caller reports "could not run" with its own exit
code (4, the same code `plumbline-gate.sh` and `live_check.py` use for it) and
its own message, which does not tell anybody to reapply anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
COMMITTED = ROOT / ".github" / "rulesets" / "main.json"

# The repository owner's standing bypass. `RepositoryRole` 5 with
# `bypass_mode: "always"` is what GitHub returns for it, and it is permanent by
# the owner's explicit decision after a ruleset once locked them out of their
# own repository. Written as a constant, and asserted in both directions below,
# so that neither "the owner was locked out again" nor "somebody granted a
# second actor a bypass" can pass as conformance.
OWNER_BYPASS = {
    "actor_id": 5,
    "actor_type": "RepositoryRole",
    "bypass_mode": "always",
}


def _contexts(ruleset: dict[str, Any]) -> set[str]:
    for rule in ruleset.get("rules") or []:
        if rule.get("type") == "required_status_checks":
            parameters = rule.get("parameters") or {}
            return {
                check.get("context", "")
                for check in parameters.get("required_status_checks") or []
            }
    return set()


def _status_check_parameters(ruleset: dict[str, Any]) -> dict[str, Any]:
    for rule in ruleset.get("rules") or []:
        if rule.get("type") == "required_status_checks":
            return dict(rule.get("parameters") or {})
    return {}


def _rule_types(ruleset: dict[str, Any]) -> set[str]:
    return {rule.get("type", "") for rule in ruleset.get("rules") or []}


def _ref_names(ruleset: dict[str, Any]) -> tuple[list[str], list[str]]:
    ref_name = (ruleset.get("conditions") or {}).get("ref_name") or {}
    return sorted(ref_name.get("include") or []), sorted(ref_name.get("exclude") or [])


class CannotJudge(Exception):
    """The live payload does not carry what the question is about.

    Raised rather than returned as a finding, because a finding is an answer
    and this is the absence of one. Everything in this module that turns
    findings into a verdict has to route this to "could not run" instead --
    which is the same stance `plumbline-gate.sh` takes when the harness
    cannot be resolved, for the same reason: a check that could not run is
    not a check that failed either, and inventing the failure it might have
    found is how issue #80 came to say the owner had been locked out of a
    repository he had not been locked out of.
    """


def bypass_findings(
    live: dict[str, Any], committed: dict[str, Any]
) -> list[str]:
    """The bypass list, checked three ways rather than compared once.

    Equality alone is not enough here and the reason is concrete: if a future
    edit put `"bypass_actors": []` back into the committed file on a day the
    owner had also been locked out of the repository, the two would agree and
    a plain comparison would report conformance on exactly the incident this
    rule exists to prevent. So the owner's bypass is asserted against both
    sides absolutely, and only *other* actors are compared.

    Raises :class:`CannotJudge` when the live payload has no `bypass_actors`
    key at all. GitHub omits it from a ruleset the caller may not administer,
    and reading that omission as an empty list is what made issue #80 report
    a lockout that had not happened. An empty list that is genuinely *there*
    is still the incident and is still a finding -- the distinction is
    between a value and a missing field, not between empty and non-empty.
    """
    findings: list[str] = []
    if "bypass_actors" not in live:
        raise CannotJudge(
            "the live ruleset payload carries no `bypass_actors` field, so "
            "whether the repository owner can still bypass the gate is not a "
            "question this payload can answer. GitHub omits the field from "
            "callers that may not administer the repository, which is what a "
            "workflow token normally is. Re-read the ruleset with credentials "
            "that can see it (`gh api repos/OWNER/REPO/rulesets/ID` as an "
            "admin) before concluding anything. Do NOT reapply the committed "
            "ruleset on the strength of this: reapplying is how the lockout "
            "this field guards against happens."
        )
    live_actors = list(live.get("bypass_actors") or [])
    committed_actors = list(committed.get("bypass_actors") or [])

    if OWNER_BYPASS not in live_actors:
        findings.append(
            "bypass_actors: the repository owner's standing bypass "
            f"({json.dumps(OWNER_BYPASS, sort_keys=True)}) is NOT enforced. "
            "An empty or owner-less bypass list is the lockout this rule exists "
            "to prevent, not a stricter gate. See .github/rulesets/README.md, "
            "\"Why the owner can bypass\"."
        )
    if OWNER_BYPASS not in committed_actors:
        findings.append(
            ".github/rulesets/main.json no longer records the repository "
            "owner's standing bypass. Reapplying the file as it stands would "
            "lock the owner out; restore it rather than reapplying."
        )

    other_live = [actor for actor in live_actors if actor != OWNER_BYPASS]
    other_committed = [actor for actor in committed_actors if actor != OWNER_BYPASS]
    for actor in other_live:
        if actor not in other_committed:
            findings.append(
                "unreviewed bypass actor: "
                f"{json.dumps(actor, sort_keys=True)} may skip the gate and is "
                "not in the committed ruleset. Only the owner's own bypass is "
                "expected; a team, an app or a second role is not."
            )
    for actor in other_committed:
        if actor not in other_live:
            findings.append(
                "bypass actor committed but not enforced: "
                f"{json.dumps(actor, sort_keys=True)}"
            )
    return findings


def differences(live: dict[str, Any], committed: dict[str, Any]) -> list[str]:
    """Every way the enforced ruleset departs from the reviewed one.

    An empty list is the only passing answer. Each finding names the property,
    what is enforced, and what was committed, in that order, because the
    enforced value is the fact and the committed value is the intent.

    The one exception to "the enforced value is the fact" is the bypass list:
    there, both sides are held against `OWNER_BYPASS` rather than only against
    each other. See :func:`bypass_findings`.
    """
    findings: list[str] = []

    def compare(label: str, live_value: object, committed_value: object) -> None:
        if live_value != committed_value:
            findings.append(
                f"{label}: enforced {live_value!r}, committed {committed_value!r}"
            )

    compare("enforcement", live.get("enforcement"), committed.get("enforcement"))
    compare("target", live.get("target"), committed.get("target"))

    findings.extend(bypass_findings(live, committed))

    live_include, live_exclude = _ref_names(live)
    committed_include, committed_exclude = _ref_names(committed)
    compare("conditions.ref_name.include", live_include, committed_include)
    compare("conditions.ref_name.exclude", live_exclude, committed_exclude)

    compare("rule types", sorted(_rule_types(live)), sorted(_rule_types(committed)))

    live_contexts, committed_contexts = _contexts(live), _contexts(committed)
    for context in sorted(committed_contexts - live_contexts):
        findings.append(
            f"required check not enforced: {context!r} is required by the "
            f"committed ruleset and not by the live one"
        )
    for context in sorted(live_contexts - committed_contexts):
        findings.append(
            f"unreviewed required check: {context!r} is enforced and is not in "
            f"the committed ruleset"
        )

    live_parameters = _status_check_parameters(live)
    committed_parameters = _status_check_parameters(committed)
    for key in ("strict_required_status_checks_policy", "do_not_enforce_on_create"):
        compare(
            f"required_status_checks.{key}",
            live_parameters.get(key),
            committed_parameters.get(key),
        )

    return findings


def report(rulesets: list[dict[str, Any]], committed: dict[str, Any]) -> tuple[int, list[str]]:
    """`(exit code, lines)` for a whole `GET /repos/{owner}/{repo}/rulesets`.

    Exit codes are distinct on purpose, so a log tells them apart without
    being read closely: `2` no active ruleset at all, `1` an active ruleset
    that is not the committed one, `4` the payload could not answer the
    question, `0` conformance.

    `4` outranks everything except `2`. A payload that cannot be judged on the
    bypass rule must not report CONFORMS on the strength of the rules it
    *could* check, and must not report DRIFTED either -- the caller's remedy
    for drift is to reapply the committed ruleset, and doing that on an
    unreadable payload is how an owner gets locked out. Any real differences
    found alongside are still printed, because losing them would be a second
    way to say less than was known.
    """
    active = [ruleset for ruleset in rulesets if ruleset.get("enforcement") == "active"]
    if not active:
        return 2, [
            "NOT ENFORCED: no active ruleset exists on this repository.",
            ".github/rulesets/main.json is committed and nothing is applying it.",
        ]
    named = [
        ruleset
        for ruleset in active
        if ruleset.get("name") == committed.get("name")
    ]
    if not named:
        return 1, [
            f"NOT ENFORCED: {len(active)} active ruleset(s), none named "
            f"{committed.get('name')!r}.",
            "Names found: "
            + ", ".join(sorted(repr(r.get("name")) for r in active)),
        ]
    lines: list[str] = []
    worst = 0
    for ruleset in named:
        try:
            found = differences(ruleset, committed)
        except CannotJudge as unanswerable:
            worst = max(worst, 4)
            lines.append(
                f"COULD NOT RUN: ruleset {ruleset.get('id')} is active, and "
                f"this payload cannot be judged against "
                f".github/rulesets/main.json."
            )
            lines.append(f"  - {unanswerable}")
            readable = differences(
                dict(ruleset, bypass_actors=committed.get("bypass_actors") or []),
                committed,
            )
            if readable:
                lines.append(
                    "  the rules this payload could be judged on differ too:"
                )
                lines.extend(f"    - {line}" for line in readable)
            lines.append(
                "  a check that could not run is not a check that passed, and "
                "not one that failed either."
            )
            continue
        if not found:
            lines.append(
                f"CONFORMS: ruleset {ruleset.get('id')} matches "
                f".github/rulesets/main.json"
            )
            continue
        worst = max(worst, 1)
        lines.append(
            f"DRIFTED: ruleset {ruleset.get('id')} is active and is not the "
            f"committed ruleset ({len(found)} difference(s)):"
        )
        lines.extend(f"  - {line}" for line in found)
    return worst, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        required=True,
        help=(
            "a file holding the JSON body of GET /repos/{owner}/{repo}/rulesets, "
            "or the expansion of one ruleset. '-' reads stdin. This program "
            "never reaches the network itself."
        ),
    )
    parser.add_argument(
        "--committed",
        default=str(COMMITTED),
        help="the reviewed ruleset (default: .github/rulesets/main.json)",
    )
    arguments = parser.parse_args(argv)

    raw = sys.stdin.read() if arguments.live == "-" else Path(arguments.live).read_text(
        encoding="utf-8"
    )
    live = json.loads(raw)
    rulesets = live if isinstance(live, list) else [live]
    committed = json.loads(Path(arguments.committed).read_text(encoding="utf-8"))

    code, lines = report(rulesets, committed)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
