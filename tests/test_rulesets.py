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

import json
import re
import unittest
from pathlib import Path

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

    def test_nobody_can_bypass_it(self):
        self.assertEqual(self.ruleset["bypass_actors"], [])

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


if __name__ == "__main__":
    unittest.main()
