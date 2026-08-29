"""The branch-protection ruleset this repository cannot apply to itself.

Whether a check can block a merge is a GitHub setting, not a file. What a file
*can* do is state the exact ruleset needed, keep it honest against the
workflow it names, and refuse to let the repository claim the gate is already
blocking when it is not. All three are tested here.

The failure mode being guarded is specific: a required status check is matched
by the name of the check run, so renaming a CI job silently turns its rule
into one that matches nothing. A rule that matches nothing looks exactly like
a rule that passes.
"""

import copy
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import ruleset_conformance

ROOT = Path(__file__).resolve().parent.parent
RULESET = ROOT / ".github" / "rulesets" / "main.json"
RULESET_DOC = ROOT / ".github" / "rulesets" / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

JOB_ID = re.compile(r"^  ([a-z][\w-]*):\s*$")
JOB_NAME = re.compile(r"^    name: (.+?)\s*$")
MATRIX_LIST = re.compile(r"^        \w+: \[(.+)\]\s*$")


def expected_check_names(source: str | None = None) -> set[str]:
    """The names GitHub will give this workflow's check runs.

    A tiny, deliberate parser rather than a YAML dependency: the core dev path
    is standard-library only, and this reads four lines of a file we own.
    """
    names: set[str] = set()
    current: str | None = None
    matrix: list[str] = []

    def flush():
        # `current` is the job id until a `name:` overrides it, which is what
        # GitHub does: a job with no `name:` gets a check run named after its
        # id. This used to start at None and only be set by `name:`, so a job
        # without one fell out of the expected set entirely — and a job that
        # is not in the expected set need not be in the ruleset, so the
        # equality below held while an unrequired job sat in the workflow.
        # "A job nobody required is a check that cannot block" is what this
        # file exists to prevent, and it was the one shape it could not see.
        if current is None:
            return
        if matrix:
            names.update(f"{current} ({value})" for value in matrix)
        else:
            names.add(current)

    text = WORKFLOW.read_text(encoding="utf-8") if source is None else source
    # Only what is under `jobs:`. `on:` has two-space keys of its own (`push`,
    # `pull_request`) and they are not jobs; the parser never noticed because
    # it only ever recorded a block that went on to declare a `name:`.
    in_jobs = False
    for line in text.splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        found = JOB_ID.match(line)
        if found:
            flush()
            current, matrix = found.group(1), []
            continue
        found = JOB_NAME.match(line)
        if found:
            current = found.group(1)
            continue
        found = MATRIX_LIST.match(line)
        if found and current:
            matrix = [value.strip().strip('"') for value in found.group(1).split(",")]
    flush()
    return names


class TestTheRulesetMatchesTheWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
        cls.rules = {rule["type"]: rule for rule in cls.ruleset["rules"]}
        cls.contexts = {
            check["context"]
            for check in cls.rules["required_status_checks"]["parameters"][
                "required_status_checks"
            ]
        }

    def test_every_ci_job_is_required_and_nothing_else_is(self):
        # Both directions. A job nobody required is a check that cannot block;
        # a context matching no job is a rule that never fires, which reads
        # identically to a rule that passes.
        self.assertEqual(self.contexts, expected_check_names())

    def test_the_audit_job_is_named_exactly(self):
        audit = [name for name in self.contexts if name.startswith("audit")]
        self.assertEqual(len(audit), 1, "the merge gate must be required, once")
        # Not `assertIn("audit", audit[0])`, which the comprehension's own
        # predicate already guaranteed. The claim worth holding is that the
        # required context is the workflow's audit job and not a context
        # someone typed by hand that no job will ever report.
        self.assertIn(audit[0], expected_check_names())

    def test_a_job_without_an_explicit_name_is_still_required(self):
        # GitHub names a check run after the job id when the job has no
        # `name:`. The parser above used to drop such a job, and a dropped job
        # is a job the ruleset need not require — the exact hole this file is
        # about, hidden inside the thing measuring it.
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("release", expected_check_names(source))
        with_extra = source + "\n  release:\n    runs-on: ubuntu-latest\n"
        self.assertIn("release", expected_check_names(with_extra))

    def test_a_merge_cannot_pass_a_check_against_a_stale_base(self):
        parameters = self.rules["required_status_checks"]["parameters"]
        self.assertTrue(parameters["strict_required_status_checks_policy"])
        self.assertFalse(parameters["do_not_enforce_on_create"])

    def test_the_checks_are_evaluated_on_a_pull_request(self):
        # Status checks gate a merge; without a pull-request rule there is no
        # merge to gate.
        self.assertIn("pull_request", self.rules)

    def test_only_the_repository_owner_can_bypass_it(self):
        """Exactly one bypass actor, and it is the repository owner's own.

        This asserted `bypass_actors == []` until 2026-08-28, and both the
        assertion and the paragraph in `.github/rulesets/README.md` arguing for
        it were wrong. The owner's standing bypass is deliberate and permanent.
        An agent once applied a ruleset that locked the owner out of their own
        repository, and restoring access took a sweep across eight rulesets in
        this portfolio; the standing instruction since is that the owner must
        always be able to bypass, in any repository. See "Why the owner can
        bypass" in that file.

        Equality with the single-element list, rather than deleting the check
        or loosening it to "the owner is in there somewhere", is what keeps
        this falsifiable in the two directions that matter:

        - a bypass granted to a **team, a GitHub App or a second role** fails
          here, which is the threat actually worth guarding;
        - the owner's bypass being **removed** fails here too, which is the
          incident that produced the rule. An empty list is not a stricter
          gate; it is the lockout.
        """
        self.assertEqual(
            self.ruleset["bypass_actors"],
            [ruleset_conformance.OWNER_BYPASS],
            "the committed ruleset must record exactly the owner's standing "
            "bypass: no second actor, and not an empty list",
        )

    def test_it_would_actually_be_enforced_if_applied(self):
        self.assertEqual(self.ruleset["enforcement"], "active")
        self.assertEqual(self.ruleset["target"], "branch")
        self.assertIn("~DEFAULT_BRANCH", self.ruleset["conditions"]["ref_name"]["include"])

    def test_history_cannot_be_rewritten_out_from_under_the_record(self):
        self.assertIn("deletion", self.rules)
        self.assertIn("non_fast_forward", self.rules)


class TestTheRepositoryDoesNotClaimTheGateIsAdvisory(unittest.TestCase):
    """The ruleset was applied 2026-08-22 (`.github/rulesets/README.md` has
    the how and the two-part verification). Before that date, every document
    mentioning the gate had to say it was advisory, and this test enforced
    that. It was rewritten the day that stopped being true, deliberately, by
    whoever applied it — the same thing its old docstring asked for. What it
    guards now is the opposite drift: a document that quietly goes back to
    saying the gate is advisory, or that started requiring it and stops
    saying so, after some future edit forgets which one is currently true."""

    def documents(self):
        for name in (
            "README.md",
            "DESIGN.md",
            ".github/rulesets/README.md",
            ".github/workflows/ci.yml",
        ):
            yield name, (ROOT / name).read_text(encoding="utf-8")

    def test_none_of_them_call_the_gate_advisory(self):
        for name, text in self.documents():
            with self.subTest(document=name):
                stated = [
                    para for para in text.split("\n\n")
                    if "branch protection" in para or "ruleset" in para.lower()
                ]
                self.assertTrue(stated, f"{name} never mentions branch protection")
                self.assertFalse(
                    any(
                        "advisory" in para or "not applied" in para.lower()
                        for para in stated
                    ),
                    f"{name} still says the gate is advisory or the ruleset is "
                    f"not applied, and it has been since 2026-08-22",
                )

    def test_the_ruleset_is_documented_where_someone_would_reapply_it(self):
        doc = RULESET_DOC.read_text(encoding="utf-8")
        self.assertIn("main.json", doc)
        self.assertIn("rulesets", doc)
        self.assertIn("Status: applied", doc)


class TestTheEnforcedRulesetIsTheCommittedOne(unittest.TestCase):
    """The step nothing checked, at either end.

    Everything above holds `.github/rulesets/main.json` to the workflow it
    names. `.github/workflows/ruleset-check.yml` held GitHub to "at least one
    active ruleset exists". Between those two is the claim the whole apparatus
    rests on -- that the ruleset being enforced is the ruleset that was
    reviewed -- and until `ruleset_conformance.py` existed, nothing compared
    them.

    The gap was not theoretical, and closing it is also how the repository
    learned its committed expectation was the wrong half. On 2026-08-28 the
    enforced ruleset (id 21223426, `updated_at` four days after it was
    created) carried a `RepositoryRole` bypass with `bypass_mode: "always"`
    while the committed file said `[]`. Nothing compared them -- and the first
    version of this comparison reported the enforced value as the fault, which
    would have been a check that failed forever against a correct repository.
    The enforced value is correct. The file, the prose and the test above were
    what needed changing.

    So the bypass rule is asserted in both directions rather than compared
    once: the owner's bypass must be present on each side independently, and
    any other actor is a finding. `test_both_sides_emptied_is_still_a_failure`
    is the case a plain equality check would pass, and it is the lockout
    incident recurring.
    """

    @classmethod
    def setUpClass(cls):
        cls.committed = json.loads(RULESET.read_text(encoding="utf-8"))

    def live(self, **overrides):
        """The committed ruleset as GitHub would return it, plus overrides."""
        ruleset = copy.deepcopy(self.committed)
        ruleset["id"] = 21223426
        ruleset.update(overrides)
        return ruleset

    def test_an_identical_ruleset_has_no_differences(self):
        self.assertEqual(
            ruleset_conformance.differences(self.live(), self.committed), []
        )

    def test_the_real_live_configuration_conforms(self):
        """2026-08-28, byte for byte from
        `gh api repos/ChelseaKR/cairn/rulesets/21223426`: the owner's standing
        bypass and nothing else. This is the configuration the repository is
        actually in, and it must read as conformance rather than as a finding.
        A check that fails forever against a correct repository is not a
        stricter check, it is a broken one.
        """
        live = self.live(bypass_actors=[ruleset_conformance.OWNER_BYPASS])
        self.assertEqual(ruleset_conformance.differences(live, self.committed), [])

    def test_a_second_bypass_actor_is_reported(self):
        """The threat actually worth guarding: a team, a GitHub App or a
        second role handed the ability to skip the gate."""
        for extra in (
            {"actor_id": 4242, "actor_type": "Team", "bypass_mode": "pull_request"},
            {"actor_id": 99, "actor_type": "Integration", "bypass_mode": "always"},
            {"actor_id": 2, "actor_type": "RepositoryRole", "bypass_mode": "always"},
        ):
            with self.subTest(actor=extra):
                drifted = self.live(
                    bypass_actors=[ruleset_conformance.OWNER_BYPASS, extra]
                )
                found = ruleset_conformance.differences(drifted, self.committed)
                self.assertEqual(len(found), 1, found)
                self.assertIn("unreviewed bypass actor", found[0])

    def test_the_owner_losing_their_bypass_is_reported(self):
        """The incident the rule exists for. An empty bypass list coming back
        from the API is the owner locked out of their own repository."""
        drifted = self.live(bypass_actors=[])
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("is NOT enforced", found[0])
        self.assertIn("lockout", found[0])

    def test_both_sides_emptied_is_still_a_failure(self):
        """The case equality alone would pass, and the whole reason the owner's
        bypass is asserted against each side rather than only compared between
        them: a tidy revert of the committed file, on a day the owner had also
        been locked out, would otherwise report conformance on exactly the
        incident this guards. Two findings, not zero.
        """
        committed = dict(self.committed, bypass_actors=[])
        drifted = self.live(bypass_actors=[])
        found = ruleset_conformance.differences(drifted, committed)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(any("is NOT enforced" in line for line in found), found)
        self.assertTrue(
            any("no longer records" in line for line in found),
            "the committed file losing the owner's bypass must be named too",
        )

    def test_the_committed_file_on_disk_records_the_owner_bypass(self):
        """Not a fixture: the actual `.github/rulesets/main.json`. Reapplying a
        ruleset file that omits the owner's bypass is one way the lockout
        happens, so the file has to be right, not only the comparison."""
        self.assertEqual(
            self.committed["bypass_actors"], [ruleset_conformance.OWNER_BYPASS]
        )

    def test_a_required_check_dropped_from_the_live_ruleset_is_reported(self):
        """The failure the whole file is named for: `audit` stops being
        required and every pull request stays green.
        """
        drifted = self.live()
        for rule in drifted["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"] = [
                    check
                    for check in rule["parameters"]["required_status_checks"]
                    if not check["context"].startswith("audit")
                ]
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("required check not enforced", found[0])
        self.assertIn("audit", found[0])

    def test_a_required_check_nobody_reviewed_is_reported(self):
        drifted = self.live()
        for rule in drifted["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"].append(
                    {"context": "something nobody committed"}
                )
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("unreviewed required check", found[0])

    def test_a_stale_base_becoming_allowed_is_reported(self):
        drifted = self.live()
        for rule in drifted["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["strict_required_status_checks_policy"] = False
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("strict_required_status_checks_policy", found[0])

    def test_a_ruleset_targeting_another_branch_is_reported(self):
        drifted = self.live()
        drifted["conditions"] = {"ref_name": {"include": ["refs/heads/scratch"], "exclude": []}}
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("conditions.ref_name.include", found[0])

    def test_a_dropped_rule_type_is_reported(self):
        drifted = self.live()
        drifted["rules"] = [
            rule for rule in drifted["rules"] if rule["type"] != "non_fast_forward"
        ]
        found = ruleset_conformance.differences(drifted, self.committed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("rule types", found[0])

    def test_no_active_ruleset_at_all_is_its_own_verdict(self):
        code, lines = ruleset_conformance.report([], self.committed)
        self.assertEqual(code, 2)
        self.assertIn("NOT ENFORCED", lines[0])
        disabled = self.live(enforcement="disabled")
        code, lines = ruleset_conformance.report([disabled], self.committed)
        self.assertEqual(code, 2, "a disabled ruleset does not block a merge")

    def test_an_active_ruleset_under_another_name_does_not_count(self):
        """The previous check counted any active ruleset. One named something
        else, requiring nothing, satisfied it.
        """
        other = {"name": "something else", "enforcement": "active", "rules": []}
        code, lines = ruleset_conformance.report([other], self.committed)
        self.assertEqual(code, 1)
        self.assertIn("none named", lines[0])

    def test_conformance_is_the_only_passing_verdict(self):
        code, lines = ruleset_conformance.report([self.live()], self.committed)
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("CONFORMS"), lines)

    def test_the_cli_exits_non_zero_and_names_what_moved(self):
        drifted = self.live(
            bypass_actors=[
                ruleset_conformance.OWNER_BYPASS,
                {"actor_id": 4242, "actor_type": "Team", "bypass_mode": "always"},
            ]
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.json"
            path.write_text(json.dumps([drifted]), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = ruleset_conformance.main(["--live", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("DRIFTED", out.getvalue())
        self.assertIn("unreviewed bypass actor", out.getvalue())
        self.assertIn("4242", out.getvalue(), "the finding names the actor")

    def test_the_workflow_calls_the_comparison_and_not_a_count(self):
        """The comparison existing is not the same as it running. This holds
        the workflow to calling it, and to no longer deciding on a count.
        """
        workflow = (
            ROOT / ".github" / "workflows" / "ruleset-check.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ruleset_conformance.py", workflow)
        self.assertNotIn("active_count", workflow)
        self.assertNotIn(
            "python3 ruleset_conformance.py --live live.json | tee",
            workflow,
            "`$?` after a pipeline is tee's status, which is 0 whatever the "
            "comparison found",
        )


if __name__ == "__main__":
    unittest.main()
