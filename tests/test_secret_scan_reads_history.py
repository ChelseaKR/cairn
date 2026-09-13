"""The secret scan named "full history" must read the full history every time.

`.github/workflows/security.yml` has always displayed its first job as
`secret-scan (gitleaks, full history)`, and README.md, docs/compliance.md and
the CHANGELOG all repeat the claim. Until 2026-09-13 the job was
`gitleaks/gitleaks-action`, which does not scan what is on disk. It picks a
commit range from the event that triggered the run:

    push, N commits   gitleaks detect --log-opts=--no-merges --first-parent BASE^..HEAD
    push, 1 commit    gitleaks detect --log-opts=-1          <- exactly one commit
    pull_request      the pull request's own commits
    schedule          no --log-opts, i.e. the whole history

Every squash merge into `main` is a one-commit push. So the true reading is
narrower than the name but not empty: the weekly `schedule` walked all 157
commits once a week, and every push and pull request in between read one
commit or one diff. A credential added on a Monday afternoon and deleted in
the next commit was invisible to the check on the pull request that carried
it, and to the push that merged it, until the following Monday morning.

`fetch-depth: 0` did not prevent that and could not. It decides how much
history `actions/checkout` puts on disk; it says nothing about how much of
that history the scanner is asked to read. A checkout deep enough to scan and
an invocation that declines to is exactly the state this workflow was in, so
the assertions below are about the *invocation*. The `fetch-depth: 0`
assertion is kept, as the necessary precondition it actually is.

Given no `--log-opts`, gitleaks runs `git log -p -U0 --full-history --all`,
which is every commit on every ref the checkout wrote to disk rather than just
the ancestry of HEAD. Measured: on a two-ref repository whose HEAD reaches one
commit, `gitleaks git .` reports two commits scanned; on the first CI run of
the fixed step it reported 213. That is a superset of `main`'s 157, which is
the direction an honest secret scan should err in.

Measured on a throwaway clone of this repository, remote removed: a random,
real-shaped AWS key planted in one commit and deleted in the next left
`gitleaks git . --log-opts=-1` exiting 0 over a tree whose contents were
byte-identical to the baseline, while `gitleaks git .` exited non-zero. The
same `gitleaks git .` over the real 157 commits of `main` is clean, so making
the check honest does not make it red.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"

# Four conformance checks elsewhere in this portfolio passed because they
# matched a tool name that appeared only inside a COMMENT. The comment above
# the scan step names both the action that was removed and the flag that must
# not return, precisely so a reader can see what is forbidden -- which means
# every assertion here has to read the file with its comments stripped, or the
# explanation would satisfy the check it explains.
_COMMENT = re.compile(r"(?m)^\s*#.*$|\s+#.*$")


def code() -> str:
    """The workflow with every comment removed."""
    return _COMMENT.sub("", WORKFLOW.read_text(encoding="utf-8"))


class TestTheScannerIsNotHandedARange(unittest.TestCase):
    def test_the_scan_is_given_no_range_at_all(self):
        self.assertIn(
            "gitleaks git . --no-banner --redact --exit-code 1",
            code(),
            "the secret scan no longer runs `gitleaks git .`. Whatever replaces it "
            "must still read the whole history on every event, not a range chosen "
            "from the thing that triggered the run.",
        )

    def test_no_commit_range_is_passed(self):
        self.assertNotIn(
            "--log-opts",
            code(),
            "`--log-opts` scopes gitleaks to a commit range. A range taken from the "
            "event is how a job called `secret-scan (gitleaks, full history)` came to "
            "read one commit on every push and every pull request.",
        )

    def test_the_event_driven_action_does_not_come_back(self):
        self.assertNotIn(
            "gitleaks/gitleaks-action",
            code(),
            "gitleaks/gitleaks-action chooses its range from the event and degrades "
            "to `--log-opts=-1` on a single-commit push, which is every squash merge "
            "into this repository's default branch.",
        )


class TestTheConditionsTheScanDependsOn(unittest.TestCase):
    def test_the_checkout_still_fetches_the_history_the_scan_walks(self):
        """Necessary, not sufficient: without it there is nothing on disk to walk."""
        self.assertRegex(
            code(),
            r"(?m)^\s*fetch-depth:\s*0\s*$",
            "`fetch-depth: 0` is gone from the secret-scan checkout, so `gitleaks "
            "git .` would read only what actions/checkout fetched. This is the "
            "precondition for a history scan; the invocation is what makes it one.",
        )

    def test_the_binary_is_checked_against_its_published_checksum(self):
        text = code()
        self.assertIn("gitleaks_checksums.txt", text)
        self.assertIn(
            "sha256sum --check --strict",
            text,
            "the gitleaks binary is downloaded and run without verifying the "
            "checksum published beside the release. Every action in this workflow is "
            "pinned to a commit for the same reason.",
        )

    def test_the_job_still_displays_the_name_it_can_now_justify(self):
        # Byte-identical on purpose. The name is a status-check context, and a
        # rename is a silently missing check rather than a failing one. It is
        # also the claim the rest of this file exists to keep true.
        self.assertIn(
            "name: secret-scan (gitleaks, full history)\n",
            WORKFLOW.read_text(encoding="utf-8"),
        )

    def test_the_retry_covers_the_download_and_not_the_verdict(self):
        # The first CI run of the fixed step died on `curl: (35) Recv failure`
        # before it reached a commit, so both fetches now retry. That is a
        # retry of a download, not a softened gate, and the difference is worth
        # a check: this file's own header promises "no `continue-on-error`, and
        # no `|| true`", and until now nothing read that promise.
        text = code()
        self.assertIn("--retry", text, "the binary download no longer retries")
        self.assertIn(
            "/tmp/gitleaks git . --no-banner --redact --exit-code 1\n",
            text,
            "the scan must be the last word: one invocation, `--exit-code 1`, "
            "nothing appended to it.",
        )
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn("|| true", text)

    def test_the_weekly_schedule_survives(self):
        # The schedule is the one event the old action already scanned in full.
        # It stays: a new detection rule against an unchanged tree is a finding
        # no commit will ever surface.
        self.assertRegex(code(), r"(?m)^\s*schedule:\s*$")
        self.assertRegex(code(), r"(?m)^\s*- cron:")


if __name__ == "__main__":
    unittest.main()
