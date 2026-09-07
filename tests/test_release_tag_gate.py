"""The release-tag gate has to be able to fail.

`.github/verify-release-tag.sh` decides whether a tag may publish a wheel to
PyPI and an image to GHCR. A check like that is worth exactly what its failing
cases are worth, and a check that verifies nothing looks identical to one that
verifies everything right up until the day it matters. This repository already
names that shape as its own worst case, in tests/test_gate_parity.py: "a gate
that is present, green, and structurally incapable of reporting what it exists
to report."

So this file does not read the script. It runs it, against tags built to be
wrong in each of the ways a release tag can be wrong: unsigned, lightweight,
signed by the wrong key, absent, and correct but naming a different commit
than the one being built.

The keys here are generated per run into a temporary directory and thrown away
with it. The maintainer's real signing key is never read, copied, or invoked:
the positive case proves the script accepts a signature from whichever key the
allowed-signers file names, and inside the temporary repository that file names
a throwaway key.

Git configuration is neutralised deliberately. Writing this on a machine with
`tag.gpgSign = true` in `~/.gitconfig` silently signed the tag that exists to
be unsigned, and "an unsigned tag is rejected" passed while testing nothing of
the kind.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "verify-release-tag.sh"
ALLOWED_SIGNERS = ROOT / ".github" / "allowed_signers"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

# The tags cut before the gate existed, which it therefore does not verify.
# Named here as well as in the workflow so that changing one without the other
# fails: a test that exempts a different list than CI exempts is a test of a
# gate nobody runs.
GRANDFATHERED = ("v0.2.0",)

# Git with no global or system configuration, so nothing in a developer's own
# ~/.gitconfig can decide the outcome of a case below.
NEUTRAL_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "PATH": os.environ.get("PATH", ""),
    "HOME": os.environ.get("HOME", ""),
}

SIGNATURE = "BEGIN SSH SIGNATURE"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=NEUTRAL_ENV,
    ).stdout.strip()


class Fixture:
    """A throwaway repository holding one tag of each interesting shape."""

    def __init__(self, directory: Path) -> None:
        self.repo = directory / "repo"
        self.repo.mkdir()
        keys = directory / "keys"
        keys.mkdir()
        self.trusted = keys / "trusted"
        self.attacker = keys / "attacker"
        for key in (self.trusted, self.attacker):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", key.name, "-f", str(key)],
                check=True, capture_output=True, env=NEUTRAL_ENV,
            )

        git(self.repo, "init", "-q", "-b", "main")
        for name, value in (
            ("user.email", "throwaway@example.invalid"),
            ("user.name", "Throwaway"),
            ("gpg.format", "ssh"),
            ("commit.gpgSign", "false"),
            ("tag.gpgSign", "false"),
            ("user.signingkey", f"{self.trusted}.pub"),
        ):
            git(self.repo, "config", name, value)

        github = self.repo / ".github"
        github.mkdir()
        algorithm, material = self.trusted.with_suffix(".pub").read_text("utf-8").split()[:2]
        (github / "allowed_signers").write_text(
            f'throwaway@example.invalid namespaces="git" {algorithm} {material}\n',
            encoding="utf-8",
        )
        (github / "verify-release-tag.sh").write_bytes(SCRIPT.read_bytes())
        git(self.repo, "add", ".github/allowed_signers", ".github/verify-release-tag.sh")
        git(self.repo, "commit", "-q", "-m", "fixture")
        self.head = git(self.repo, "rev-parse", "HEAD")

        git(self.repo, "tag", "-s", "v9.0.0", "-m", "signed by the trusted key")
        git(self.repo, "tag", "-a", "v9.0.1", "-m", "annotated, never signed")
        git(self.repo, "tag", "v9.0.2")
        git(self.repo, "-c", f"user.signingkey={self.attacker}.pub",
            "tag", "-s", "v9.0.3", "-m", "signed by a key nobody trusts")
        git(self.repo, "tag", "-a", GRANDFATHERED[0], "-m", "stands in for real history")

    def run(self, **environment: str) -> subprocess.CompletedProcess[str]:
        env = dict(NEUTRAL_ENV)
        env["ALLOWED_SIGNERS"] = ".github/allowed_signers"
        env.update(environment)
        return subprocess.run(
            ["bash", ".github/verify-release-tag.sh"],
            cwd=self.repo, capture_output=True, text=True, env=env,
        )


class GateCase(unittest.TestCase):
    fixture: Fixture

    @classmethod
    def setUpClass(cls) -> None:
        if sys.platform == "win32":  # pragma: no cover - the gate runs on ubuntu
            raise unittest.SkipTest("exercises the POSIX bash gate with ssh-keygen")
        cls.directory = TemporaryDirectory()
        cls.fixture = Fixture(Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "directory"):
            cls.directory.cleanup()


class TestTheGateAcceptsWhatItShould(GateCase):
    def test_the_fixture_is_in_the_shape_every_case_below_assumes(self):
        # A negative control that does not apply reads exactly like a pass, so
        # the malformed tags are asserted malformed rather than assumed to be.
        repo = self.fixture.repo
        self.assertEqual(git(repo, "cat-file", "-t", "v9.0.2"), "commit",
                         "v9.0.2 must be a lightweight tag")
        for annotated in ("v9.0.0", "v9.0.1", "v9.0.3", GRANDFATHERED[0]):
            self.assertEqual(git(repo, "cat-file", "-t", annotated), "tag", annotated)
        for signed in ("v9.0.0", "v9.0.3"):
            self.assertIn(SIGNATURE, git(repo, "cat-file", "-p", signed), signed)
        for unsigned in ("v9.0.1", GRANDFATHERED[0]):
            self.assertNotIn(SIGNATURE, git(repo, "cat-file", "-p", unsigned), unsigned)

    def test_a_signed_tag_naming_the_built_commit_passes(self):
        result = self.fixture.run(RELEASE_TAG="v9.0.0", EXPECT_COMMIT=self.fixture.head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified", result.stdout)

    def test_a_dispatch_from_a_tag_ref_resolves_that_tag(self):
        result = self.fixture.run(REF_TYPE="tag", REF_NAME="v9.0.0",
                                  EXPECT_COMMIT=self.fixture.head)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_named_grandfathered_tag_is_skipped_and_says_so(self):
        result = self.fixture.run(RELEASE_TAG=GRANDFATHERED[0],
                                  EXPECT_COMMIT=self.fixture.head,
                                  GRANDFATHERED_TAGS=" ".join(GRANDFATHERED))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("predates", result.stdout)


class TestTheGateRejectsWhatItShould(GateCase):
    def rejects(self, expected: str, **environment: str) -> None:
        result = self.fixture.run(**environment)
        self.assertNotEqual(
            result.returncode, 0,
            f"this would have published:\n{result.stdout}\n{result.stderr}",
        )
        self.assertIn(expected, result.stdout + result.stderr)

    def test_an_unsigned_annotated_tag_is_refused(self):
        self.rejects("not signed by a key listed",
                     RELEASE_TAG="v9.0.1", EXPECT_COMMIT=self.fixture.head)

    def test_a_lightweight_tag_is_refused(self):
        self.rejects("not an annotated tag object",
                     RELEASE_TAG="v9.0.2", EXPECT_COMMIT=self.fixture.head)

    def test_a_tag_signed_by_an_untrusted_key_is_refused(self):
        self.rejects("not signed by a key listed",
                     RELEASE_TAG="v9.0.3", EXPECT_COMMIT=self.fixture.head)

    def test_a_dispatch_from_a_branch_publishes_nothing(self):
        self.rejects("No release tag could be resolved",
                     REF_TYPE="branch", REF_NAME="main", EXPECT_COMMIT=self.fixture.head)

    def test_a_tag_that_does_not_exist_is_refused(self):
        self.rejects("does not exist", RELEASE_TAG="v9.9.9",
                     EXPECT_COMMIT=self.fixture.head)

    def test_a_verified_tag_that_names_another_commit_is_refused(self):
        # Signature verification alone passes here. Without this the gate
        # would prove that some tag was signed while the build ran from
        # something else, which is a check that cannot fail on the thing it
        # exists to catch.
        self.rejects("Refusing to publish", RELEASE_TAG="v9.0.0", EXPECT_COMMIT="0" * 40)

    def test_the_grandfather_list_cannot_be_widened_into_a_pattern(self):
        for widened in ("v*", "v9.0.1*", "*"):
            with self.subTest(entry=widened):
                self.rejects("is not a literal", RELEASE_TAG="v9.0.1",
                             EXPECT_COMMIT=self.fixture.head, GRANDFATHERED_TAGS=widened)

    def test_an_empty_allowed_signers_file_cannot_wave_a_tag_through(self):
        (self.fixture.repo / ".github" / "empty_signers").write_text("", encoding="utf-8")
        self.rejects("missing or empty", RELEASE_TAG="v9.0.0",
                     EXPECT_COMMIT=self.fixture.head,
                     ALLOWED_SIGNERS=".github/empty_signers")


class TestTheWorkflowActuallyUsesTheGate(unittest.TestCase):
    """The script above can be perfect and unreferenced."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_the_workflow_runs_the_script(self):
        self.assertIn(".github/verify-release-tag.sh", self.text)

    def test_every_publishing_job_waits_for_it(self):
        # A verification job nothing depends on is a job that reports and
        # never blocks, which is the same shape as no job at all.
        for job in ("pypi:", "container:"):
            start = self.text.index(f"  {job}")
            end = self.text.index("    steps:", start)
            self.assertIn("needs: [verify-tag]", self.text[start:end], job)

    def test_both_publishing_jobs_build_the_verified_commit(self):
        self.assertEqual(self.text.count("ref: ${{ needs.verify-tag.outputs.commit }}"), 2)

    def test_the_workflow_grandfathers_exactly_what_this_file_grandfathers(self):
        declared = re.search(r'GRANDFATHERED_TAGS:\s*"([^"]*)"', self.text)
        self.assertIsNotNone(declared, "the workflow sets no GRANDFATHERED_TAGS")
        self.assertEqual(declared.group(1).split(), list(GRANDFATHERED))

    def test_the_committed_allowed_signers_names_a_key(self):
        lines = [line for line in ALLOWED_SIGNERS.read_text("utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertTrue(lines, "allowed_signers is empty")
        self.assertTrue(all("ssh-" in line for line in lines), lines)

    def test_the_grandfathered_tags_are_the_ones_that_cannot_pass(self):
        # The list is history, not preference: every tag on it has to be one
        # this repository actually cut, and the whole point of the entry is
        # that the tag cannot be made to verify without rewriting it.
        self.assertEqual(GRANDFATHERED, ("v0.2.0",))

    def test_the_readme_does_not_say_signing_is_absent(self):
        """The conformance row read `**Not in place:** signed tags.`

        It had been true, and stopped being true when this gate landed: the script
        above refuses a lightweight tag, an unsigned one, and one signed by a key
        outside `allowed_signers`, and every publishing job waits for it. Nothing
        read that sentence, so the row went on understating a control the repository
        actually enforces -- the same drift as the README's version prose, in the
        other direction. A reader deciding whether to depend on this project reads
        the conformance table, and a project that undersells its own release
        integrity is describing a different project.
        """
        readme = (ROOT / "README.md").read_text("utf-8")
        self.assertNotIn("**Not in place:** signed tags", readme)

    def test_the_readme_names_exactly_the_tags_the_gate_exempts(self):
        """The row states which tag is exempt. That claim is checkable, so check it.

        Naming the exemption is what makes the corrected sentence honest rather than
        a boast, and an exemption list a reader can see is only useful while it is
        the list CI uses. This holds the README to `GRANDFATHERED`, which
        `test_the_workflow_grandfathers_exactly_what_this_file_grandfathers` already
        holds to the workflow -- so all three move together or the suite is red.
        """
        readme = (ROOT / "README.md").read_text("utf-8")
        claim = re.search(
            r"\*\*The one exemption is history, named literally:\*\*(.+?)`GRANDFATHERED_TAGS`",
            readme,
            re.S,
        )
        self.assertIsNotNone(claim, "the README no longer names the grandfathered tag")
        named = re.findall(r"`(v\d+\.\d+\.\d+)`", claim.group(1))
        self.assertEqual(sorted(named), sorted(GRANDFATHERED))


if __name__ == "__main__":
    unittest.main()
