"""The Dockerfile, docs/deployment.md's fenced illustration of it, and
release.yml agree with each other — and, separately from what a unit test
can prove, with reality: `.github/workflows/ci.yml`'s `image` job actually
builds this file and asks the running container the demo question, on
every change. Building an image needs a Docker daemon this suite cannot
assume is present, so that check lives in CI rather than here; what
belongs here is everything checkable from the files alone, so a drift
between what the page shows and what actually ships is a test failure
rather than something a reader has to notice by hand.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DEPLOYMENT = ROOT / "docs" / "deployment.md"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

DOCKERFILE_BLOCK = re.compile(r"```dockerfile\n(.*?)```", re.DOTALL)


class TestTheDockerfileIsWhatTheDocsShow(unittest.TestCase):
    def test_the_page_has_exactly_one_dockerfile_block(self):
        blocks = DOCKERFILE_BLOCK.findall(DEPLOYMENT.read_text(encoding="utf-8"))
        self.assertEqual(len(blocks), 1, "the page should show the Dockerfile exactly once")

    def test_the_documented_block_has_the_same_directives_as_the_real_file(self):
        # Not byte for byte: the real file explains itself in comments this
        # page's own surrounding prose already covers, and duplicating them
        # inside the fence would just be two copies of the same rationale to
        # keep in sync. What has to agree is the part that actually runs —
        # every non-comment, non-blank line, in order.
        def directives(text):
            return [
                line for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]

        block = DOCKERFILE_BLOCK.findall(DEPLOYMENT.read_text(encoding="utf-8"))[0]
        self.assertEqual(directives(block), directives(DOCKERFILE.read_text(encoding="utf-8")))

    def test_the_port_matches_cairn_serve_s_own_default(self):
        from cairn.cli import build_parser

        default_port = build_parser().parse_args(["serve"]).port
        exposed = int(
            re.search(r"^EXPOSE (\d+)$", DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)
            .group(1)
        )
        self.assertEqual(exposed, default_port, "EXPOSE drifted from --port's own default")

    def test_it_binds_every_interface_not_just_loopback(self):
        # The one line in this file that would be a real bug reversed: the
        # documented reason (docs/deployment.md, right after the block) is
        # that the container's own network namespace makes 127.0.0.1
        # unreachable from outside it.
        self.assertIn('"--host", "0.0.0.0"', DOCKERFILE.read_text(encoding="utf-8"))

    def test_it_does_not_run_as_root(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("USER cairn", text)
        # The USER switch has to come after both the steps that need root
        # (installing into system site-packages, writing the baked-in
        # index) and before the ENTRYPOINT that actually answers a
        # network request — order in the file is the order Docker runs it.
        self.assertLess(text.index("USER cairn"), text.index("ENTRYPOINT"))
        self.assertLess(text.index("pip install"), text.index("USER cairn"))

    def test_dockerignore_excludes_version_control(self):
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn(".git", ignore)


class TestTheReleaseWorkflow(unittest.TestCase):
    """Structural claims a full YAML parse can check without a network call
    or a registry credential — the same spirit as tests/test_rulesets.py's
    tiny parser: everything this repository can verify about itself with no
    dependency beyond the standard library, checked, so an edit that breaks
    the shape of this file fails here rather than at the next real release.
    """

    @classmethod
    def setUpClass(cls):
        text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        cls.text = text

    def test_it_fires_on_a_published_release(self):
        self.assertIn("release:", self.text)
        self.assertIn("types: [published]", self.text)

    def test_the_pypi_job_authenticates_by_oidc_not_a_stored_secret(self):
        self.assertIn("id-token: write", self.text)
        # The negative half of the claim: nothing here should be minting a
        # PyPI credential from a secret, which is the thing trusted
        # publishing exists to make unnecessary.
        self.assertNotIn("PYPI_TOKEN", self.text)
        self.assertNotIn("PYPI_API_TOKEN", self.text)

    def test_the_release_tag_is_checked_against_the_package_version(self):
        self.assertIn("cairn.__version__", self.text)

    def test_the_container_job_pushes_both_the_tag_and_latest(self):
        self.assertIn("ghcr.io/chelseakr/cairn:latest", self.text)
        self.assertIn("github.event.release.tag_name", self.text)

    def test_every_action_is_pinned_to_a_commit(self):
        # Matches the convention every other workflow in this repository
        # follows — see ci.yml's own header comment for the argument.
        for match in re.finditer(r"uses:\s*([^\s@]+)@([^\s#]+)", self.text):
            action, ref = match.groups()
            with self.subTest(action=action):
                self.assertRegex(
                    ref, r"^[0-9a-f]{40}$", f"{action} is pinned to {ref!r}, not a commit SHA"
                )


if __name__ == "__main__":
    unittest.main()
