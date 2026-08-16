"""The audit interlock: pinned, resolved at run time, and failing closed.

Four properties, each of which is a thing that quietly goes wrong otherwise:

1. **One file is the source of truth.** A laptop and a CI runner read the same
   `plumbline.pin`. Two places recording two versions is where "works locally,
   fails in CI" comes from, and where its worse twin comes from.
2. **The pin is an exact commit.** A branch or a tag can move, and then a
   green gate today means something different tomorrow.
3. **The auditor is not a dependency.** Nothing in the engine imports it,
   nothing in the packaging requires it, and the core path never fetches it.
   The thing auditing this repository must not be movable by this
   repository's own dependency resolution.
4. **It fails closed.** Every way the harness can be unresolvable ends in a
   non-zero exit, not a skip. These tests run the real runner against real
   broken pins to prove it, because a fail-closed claim that is only asserted
   in a comment is a fail-open gate waiting for a bad day.

Nothing here needs the network: the failure paths are exercised with
references that cannot resolve locally, and the passing path (which does need
the harness) is CI's job, not this suite's.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from cairn.record import bundle_checksums

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "plumbline.pin"
RUNNER = ROOT / "plumbline-gate.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TARGET = ROOT / "plumbline" / "target.toml"
BUNDLE = ROOT / "plumbline" / "bundle"

EXIT_ENVIRONMENT = 4  # the harness's code for "the gate did not run"

COMMIT = re.compile(r"^[0-9a-f]{40}$")


def read_pin(text: str) -> dict[str, str]:
    """The pin file, parsed the way the runner parses it."""
    values = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def run_gate(pin_text: str | None, *, cache: Path) -> subprocess.CompletedProcess:
    """Run the real runner against a pin, from a throwaway cache directory."""
    with tempfile.TemporaryDirectory() as tmp:
        pin_path = Path(tmp) / "plumbline.pin"
        if pin_text is not None:
            pin_path.write_text(pin_text, encoding="utf-8")
        return subprocess.run(
            [str(RUNNER)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "PLUMBLINE_PIN_FILE": str(pin_path),
                "PLUMBLINE_CACHE_DIR": str(cache),
            },
        )


class TestPinFile(unittest.TestCase):
    def test_the_pin_exists_and_names_a_harness_a_commit_and_a_target(self):
        self.assertTrue(PIN.is_file(), "the pin file is the whole contract")
        pin = read_pin(PIN.read_text(encoding="utf-8"))
        for key in ("repo", "ref", "config"):
            self.assertIn(key, pin, f"the pin must set {key!r}")
        self.assertTrue(pin["repo"].endswith(".git"))
        self.assertTrue(TARGET.is_file(), "the pinned config must exist")

    def test_the_ref_is_an_exact_commit_not_something_that_can_move(self):
        pin = read_pin(PIN.read_text(encoding="utf-8"))
        self.assertRegex(pin["ref"], COMMIT, "pin a 40-character commit, not a branch or tag")

    def test_nothing_else_records_a_harness_version(self):
        # Grep the tracked tree for a second commit hash claiming to be the
        # harness: a version recorded in two places is a version that will
        # disagree with itself.
        pin_ref = read_pin(PIN.read_text(encoding="utf-8"))["ref"]
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
        elsewhere = []
        scanned = 0
        for name in tracked:
            path = ROOT / name
            if path == PIN or not path.is_file():
                continue
            # Bytes, not decoded text. A file the scan could not decode used
            # to be skipped, and a skipped file is indistinguishable from a
            # clean one — the population quietly shrinking is how a scan comes
            # to report "no findings" because it looked at nothing. A commit
            # hash is ASCII hex, so it is findable without decoding anything.
            scanned += 1
            for found in re.findall(rb"\b[0-9a-f]{40}\b", path.read_bytes()):
                if found.decode("ascii") != pin_ref:
                    continue
                elsewhere.append(name)
        self.assertGreater(scanned, 10, "the scan ran on almost nothing; it proves nothing")
        self.assertEqual(elsewhere, [], "the pinned commit is repeated outside the pin file")


class TestTheAuditorIsNotADependency(unittest.TestCase):
    def test_the_engine_does_not_import_it(self):
        for path in (ROOT / "cairn").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import plumbline", source, f"{path} imports the auditor")
            self.assertNotIn("from plumbline", source, f"{path} imports the auditor")

    def test_the_packaging_does_not_require_it(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        requirements = pyproject.split("[project.optional-dependencies]")[0]
        self.assertNotIn("plumbline", requirements)

    def test_the_resolved_harness_is_never_committed(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".plumbline-cache", ignored)
        tracked = subprocess.run(
            ["git", "ls-files", ".plumbline-cache"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(tracked.strip(), "")


class TestItFailsClosed(unittest.TestCase):
    """The runner, run for real, against pins that cannot resolve."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.cache = Path(cls._tmp.name) / "cache"
        cls.good = PIN.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assertFailedBeforeScoring(self, result, because):
        self.assertEqual(
            result.returncode,
            EXIT_ENVIRONMENT,
            f"expected the environment-failure exit code {because}:\n{result.stderr}",
        )
        self.assertIn("FAILED before scoring", result.stderr)
        self.assertNotIn("PASS", result.stdout)

    def test_an_unreachable_harness_fails_rather_than_skipping(self):
        pin = re.sub(r"(?m)^repo = .*$", "repo = file:///nonexistent/harness.git", self.good)
        self.assertFailedBeforeScoring(
            run_gate(pin, cache=self.cache), "when the harness cannot be fetched"
        )

    def test_a_commit_the_harness_does_not_have_fails(self):
        pin = re.sub(r"(?m)^ref  = .*$", "ref = " + "0" * 39 + "1", self.good)
        self.assertFailedBeforeScoring(
            run_gate(pin, cache=self.cache), "when the pinned commit is absent"
        )

    def test_a_moving_reference_is_refused_outright(self):
        pin = re.sub(r"(?m)^ref  = .*$", "ref = main", self.good)
        result = run_gate(pin, cache=self.cache)
        self.assertFailedBeforeScoring(result, "when the ref is a branch")
        self.assertIn("not a 40-character commit hash", result.stderr)

    def test_a_missing_pin_file_fails(self):
        self.assertFailedBeforeScoring(
            run_gate(None, cache=self.cache), "when there is no pin file"
        )

    def test_a_pin_with_no_target_fails(self):
        pin = re.sub(r"(?m)^config = .*$", "", self.good)
        self.assertFailedBeforeScoring(
            run_gate(pin, cache=self.cache), "when the pin names no target"
        )


class TestTheCiGateIsWiredToFail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        # Comments explain the choices at length; the checks below are about
        # what the workflow *does*, so strip them first.
        cls.active = "\n".join(
            line for line in cls.text.splitlines() if not line.lstrip().startswith("#")
        )

    def test_the_gate_job_exists_and_runs_the_pinned_runner(self):
        self.assertIn("plumbline-gate.sh", self.active)
        self.assertIn("audit:", self.active)

    def test_the_gate_cannot_be_skipped_or_softened(self):
        self.assertNotIn("continue-on-error", self.active)
        audit = self.active.split("audit:", 1)[1]
        self.assertNotIn("if:", audit.split("Keep the report")[0])

    def test_nothing_in_the_workflow_sets_the_bypass(self):
        # `PLUMBLINE_SRC` skips resolution entirely: the pin is not read and
        # the run is graded by whatever directory it names. The runner warns
        # and proceeds, which is right for the harness's own developers and
        # wrong for a merge gate.
        self.assertNotIn("PLUMBLINE_SRC=", self.active, "that flag bypasses the pin")
        self.assertNotIn("PLUMBLINE_SRC:", self.active, "that flag bypasses the pin")

    def test_every_gate_invocation_unsets_the_bypass_first(self):
        # Not enough that this workflow does not set it. The variable can
        # arrive from a repository-level variable or a self-hosted runner's
        # own environment, and the runner is vendored byte for byte from
        # Plumbline, so the pin cannot be enforced by editing it. `env -u`
        # enforces it at the call site instead, whatever put the variable
        # there. Every call, not most of them.
        calls = [
            line.strip()
            for line in self.active.splitlines()
            if "./plumbline-gate.sh" in line
        ]
        self.assertTrue(calls, "the workflow does not run the gate at all")
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("env -u PLUMBLINE_SRC", call)

    def test_the_vendored_runner_is_checked_against_the_resolved_harness(self):
        # "Vendored verbatim" is claimed in three documents and is the whole
        # reason the bypass is not simply patched out of the runner. The audit
        # job — the one job with a resolved harness — diffs the two.
        audit = self.active.split("audit:", 1)[1]
        self.assertIn("gate/plumbline-gate.sh", audit)
        self.assertIn("diff -u", audit)

    def test_the_reason_for_failing_rather_than_skipping_is_written_down(self):
        self.assertIn("skip", self.text.lower())
        self.assertIn("not a gate that passed", self.text)

    def test_the_core_path_is_proven_to_work_without_the_auditor(self):
        core = self.active.split("core:", 1)[1].split("interface:", 1)[0]
        self.assertIn("unittest discover", core)
        self.assertIn("ruff check", core)
        self.assertIn(".plumbline-cache", core, "the core job checks it never resolved one")
        self.assertIn("-eq 4", core, "the core job proves the gate fails in that condition")

    def test_the_harness_cache_key_is_the_pin_not_a_branch(self):
        self.assertIn("hashFiles('plumbline.pin')", self.active)


class TestTheEvidenceIsIntact(unittest.TestCase):
    """Cairn writes the bundle's checksums, so Cairn checks them too. The
    auditor refusing to score is the backstop, not the only guard."""

    def test_the_committed_bundle_verifies_against_its_own_checksums(self):
        recorded = json.loads((BUNDLE / "checksums.json").read_text(encoding="utf-8"))
        recomputed = bundle_checksums(BUNDLE)
        self.assertEqual(recorded["files"], recomputed["files"], "a bundle file was edited")
        self.assertEqual(recorded["bundle_sha256"], recomputed["bundle_sha256"])

    def test_every_recorded_response_belongs_to_an_item(self):
        items = [json.loads(line) for line in (BUNDLE / "items.jsonl").read_text().splitlines()]
        responses = [
            json.loads(line) for line in (BUNDLE / "responses.jsonl").read_text().splitlines()
        ]
        # Two empty files satisfy `[] == []` and `all([])`, which is the
        # whole check. The population is the committed question set.
        self.assertGreaterEqual(len(items), 20, "the evidence bundle came back empty")
        self.assertEqual([i["id"] for i in items], [r["id"] for r in responses])
        self.assertTrue(all(r["response"].strip() for r in responses))

    def test_every_citation_resolves_to_a_declared_source(self):
        sources = {
            json.loads(line)["id"]
            for line in (BUNDLE / "sources.jsonl").read_text().splitlines()
        }
        citation = re.compile(r"\[([A-Za-z][A-Za-z0-9._:-]*)\]")
        cited = set()
        for line in (BUNDLE / "responses.jsonl").read_text().splitlines():
            cited.update(citation.findall(json.loads(line)["response"]))
        self.assertTrue(cited, "the evidence should contain citations")
        self.assertLessEqual(cited, sources, "a response cites a source that does not exist")

    def test_the_interface_snapshot_declares_its_colours(self):
        snapshot = (BUNDLE / "interface.html").read_text(encoding="utf-8")
        self.assertIn('id="plumbline-contrast"', snapshot)
        block = snapshot.split('id="plumbline-contrast">', 1)[1].split("</script>", 1)[0]
        pairs = json.loads(block)
        self.assertTrue(pairs)
        self.assertTrue(any("(dark)" in p["name"] for p in pairs), "both presentations")
        self.assertTrue(any("(light)" in p["name"] for p in pairs))


if __name__ == "__main__":
    unittest.main()
