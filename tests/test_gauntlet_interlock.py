"""The gauntlet interlock, checked offline.

The full gate needs a checkout of the pinned harness. What the core dev path
can hold without it — and therefore what most of these tests hold — is the
same discipline tests/test_interlock.py applies to the audit side: the pin
says exactly one thing, the suites are structurally sound, the gate fails
closed when its harness cannot be resolved, and nothing here can drift from
those facts quietly.

`TestTheFullGate` is the one that needs the checkout, and it used to say
`"Runs only where a sibling checkout exists; CI runs it always."` **No CI job
ran it.** It looked for `../gauntlet`, a sibling of the repository root, and:

- the jobs that run the test suite (`core` twice over the matrix, and the
  nightly `core-os` canary in `os-canary.yml`) check out this repository and
  nothing else, so no sibling exists in any of them;
- the `gauntlet` job clones the harness to `$RUNNER_TEMP/gauntlet` and passes
  it as `GAUNTLET_CHECKOUT` — the variable `gauntlet-gate.sh` resolves first
  and this file did not read — and then runs the gate directly rather than
  running unittest at all.

So it skipped in every environment that existed: in CI for want of a sibling,
and on a laptop unless somebody happened to have a checkout at exactly the
pinned commit, which is the same "ran on a laptop, nowhere else, while its
docstring said it ran in CI" that `.github/workflows/ci.yml` already records
closing for `tests/test_audit_guard.py`.

Both halves are fixed below: the skip now resolves a checkout the way the
gate itself does, and `TestCiRunsTheFullGateSuite` holds the workflow to
running this module in the one job that has a checkout — so the docstring's
claim is checked rather than believed.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "gauntlet.pin"
SUITES = ROOT / "gauntlet" / "cases"
GATE = ROOT / "gauntlet-gate.sh"

# The gates gauntlet ships (read from the pinned harness's own README at pin
# time). A suite naming a gate outside this set is a typo that would exit 2
# in CI — "harness could not run" — instead of failing loudly here.
KNOWN_GATES = {"grounding", "adversarial", "refusal", "false_positive", "golden"}

SHA256_RE = re.compile(r"^commit = \"([0-9a-f]{40})\"$", re.M)

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def pinned_commit() -> str:
    return SHA256_RE.search(PIN.read_text(encoding="utf-8")).group(1)


def resolved_checkout() -> Path | None:
    """A checkout at the pinned commit, found the way the gate finds one.

    `gauntlet-gate.sh` reads `$GAUNTLET_CHECKOUT` first and falls back to
    `../gauntlet` then `./gauntlet-checkout`. This used to look only at the
    sibling, which is why it never ran in the one CI job that has a checkout:
    that job passes the path in the environment variable.
    """
    commit = pinned_commit()
    candidates = []
    from_env = os.environ.get("GAUNTLET_CHECKOUT")
    if from_env:
        candidates.append(Path(from_env))
    candidates += [ROOT.parent / "gauntlet", ROOT / "gauntlet-checkout"]
    for candidate in candidates:
        if not (candidate / ".git").is_dir():
            continue
        head = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head.returncode == 0 and head.stdout.strip() == commit:
            return candidate
    return None


class TestThePin(unittest.TestCase):
    def test_the_pin_names_a_repo_an_exact_commit_and_paths(self):
        text = PIN.read_text(encoding="utf-8")
        self.assertIn('repository = "ChelseaKR/gauntlet"', text)
        match = SHA256_RE.search(text)
        self.assertIsNotNone(match, "pin must name an exact 40-hex commit")
        for key in ("suites = ", "target = ", "results = "):
            self.assertIn(key, text)

    def test_the_pinned_commit_apars_exactly_once_in_the_tree(self):
        """One place names the commit; a second unreviewed copy is how a pin
        stops meaning anything."""
        text = PIN.read_text(encoding="utf-8")
        commit = SHA256_RE.search(text).group(1)
        # Tracked files plus untracked-but-real ones: the pin itself is
        # often new when this runs, and a check that silently skips it would
        # be a check that never ran.
        listing = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        hits = []
        for name in listing.stdout.splitlines():
            path = ROOT / name
            if not path.is_file() or name.startswith((".cairn", "plumbline/bundle")):
                continue
            if commit in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(name)
        self.assertEqual(hits, ["gauntlet.pin"])


class TestTheSuites(unittest.TestCase):
    def test_only_yaml_files_and_no_yml_lookalikes(self):
        # Gauntlet refuses `.yml` rather than skipping it; this keeps the
        # directory free of the file that would turn a run into an error.
        for path in SUITES.iterdir():
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.suffix, ".yaml", str(path))

    def test_every_suite_declares_its_shape_and_peers(self):
        for path in sorted(SUITES.glob("*.yaml")):
            with self.subTest(suite=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertRegex(text, r"(?m)^suite: \S+")
                self.assertRegex(text, r"(?m)^version: \d+")
                threshold = re.search(r"(?m)^threshold: ([0-9.]+)$", text)
                self.assertIsNotNone(threshold, path.name)
                self.assertGreater(float(threshold.group(1)), 0.0)
                gate = re.search(r"(?m)^gate: (\w+)$", text).group(1)
                self.assertIn(gate, KNOWN_GATES, path.name)
                en = len(re.findall(r"(?m)^    language: en$", text))
                es = len(re.findall(r"(?m)^    language: es$", text))
                declared_single = "single-language:" in text
                if declared_single:
                    # A suite may serve one language only when it says so in
                    # its own header with a reason — parity is the default,
                    # not a straitjacket over an honest gap.
                    self.assertTrue(
                        en > 0 or es > 0, f"{path.name}: no cases at all"
                    )
                else:
                    self.assertGreaterEqual(en, 1, f"{path.name}: no English case")
                    self.assertGreaterEqual(es, 1, f"{path.name}: no Spanish case")
                    self.assertEqual(
                        en, es,
                        f"{path.name}: English and Spanish cases are peers, "
                        f"added together",
                    )

    def test_adversarial_markers_never_appear_in_corpus_answers(self):
        """A marker that the engine legitimately quotes would fail the gate
        forever and teach nobody anything."""
        adversarial = (SUITES / "adversarial.yaml").read_text(encoding="utf-8")
        # Only quoted strings that carry a digit: planted amounts are the
        # markers that matter here, and a looser grab pulls in YAML's own
        # commas between array items.
        markers = [
            found
            for found in re.findall(r'"([^"]+)"', adversarial)
            if any(char.isdigit() for char in found)
        ]
        self.assertTrue(markers, "no numeric markers found in the adversarial suite")
        from cairn.config import Config
        from cairn.engine import ask
        from cairn.index import build_index

        index = build_index("corpus/demo")
        for marker in markers:
            with self.subTest(marker=marker):
                result = ask("How much is the monthly grocery allowance?",
                             index, Config())
                if result.answer.kind == "grounded":
                    self.assertNotIn(marker, result.answer.text)


COMMIT_SENTINEL = SHA256_RE.search(PIN.read_text(encoding="utf-8")).group(1)


@unittest.skipIf(
    sys.platform == "win32",
    "gauntlet-gate.sh is invoked as ./gauntlet-gate.sh, relying on the OS to "
    "read its #!/bin/sh shebang and dispatch to sh — a POSIX exec behaviour "
    "Windows does not have outside a shell. Same gap tests/test_interlock.py "
    "already states for plumbline-gate.sh, found here for gauntlet-gate.sh "
    "the same way: a real Windows CI run, not a guess.",
)
class TestTheGateFailsClosed(unittest.TestCase):
    def test_no_resolvable_checkout_is_exit_four_not_agreement(self):
        completed = subprocess.run(
            [str(GATE)],
            capture_output=True, text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                # A checkout that exists but is not at the pin must be
                # refused just as hard as a missing one.
                "GAUNTLET_CHECKOUT": "/nonexistent/gauntlet",
            },
            timeout=60,
        )
        self.assertEqual(completed.returncode, 4, completed.stderr)
        self.assertIn("is not at the pinned commit", completed.stderr)
        self.assertIn(COMMIT_SENTINEL, completed.stderr)


@unittest.skipUnless(
    resolved_checkout() is not None,
    "no checkout of the harness at the pinned commit (set GAUNTLET_CHECKOUT, "
    "or put one at ../gauntlet or ./gauntlet-checkout)",
)
@unittest.skipIf(
    sys.platform == "win32",
    "gauntlet-gate.sh needs a shell to exec its shebang; see "
    "TestTheGateFailsClosed's skip reason above.",
)
class TestTheFullGate(unittest.TestCase):
    """Runs wherever a checkout at the pinned commit is resolvable, by the
    gate's own resolution order — which is what makes the `gauntlet` CI job
    one of those places. See the module docstring for what this said before,
    and why nothing ran it."""

    def test_the_gate_passes_against_the_pinned_checkout(self):
        checkout = resolved_checkout()
        self.assertIsNotNone(checkout, "the class skip should have caught this")
        # The environment is inherited, and that is a correction rather than a
        # convenience. This used to hand the gate a hand-built
        # `{"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}` -- a
        # laptop's PATH, with Homebrew on it -- and the first CI run of this
        # test, which is to say the first run of it anywhere, failed with
        #
        #     gauntlet-gate.sh: 78: uv: not found        (exit 127)
        #
        # because `astral-sh/setup-uv` puts uv somewhere no hard-coded list
        # can predict. The gate needs a real PATH, a HOME for uv's cache, and
        # the UV_* variables the runner sets; enumerating those by hand is the
        # same guess that just failed. `GAUNTLET_CHECKOUT` is passed through
        # from the environment for the same reason it always was.
        environment = dict(os.environ)
        completed = subprocess.run(
            [str(GATE)], capture_output=True, text=True,
            env=environment,
            timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("overall: PASS", completed.stdout)


class TestCiRunsTheFullGateSuite(unittest.TestCase):
    """The claim, checked.

    A skipped test and a passing test are one green line apart, and the
    difference lives in a log nobody opens — the same argument
    `.github/workflows/ci.yml` makes about a skipped gate. `TestTheFullGate`
    can only run where a checkout exists, and exactly one job has one, so
    that job has to be the one that runs it.
    """

    def test_the_gauntlet_job_runs_this_module(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "tests.test_gauntlet_interlock",
            workflow,
            "no CI job runs this module, so TestTheFullGate is skipped "
            "everywhere and its assertions are never made",
        )

    def test_the_step_that_runs_it_names_the_checkout(self):
        """`GAUNTLET_CHECKOUT` is what makes the checkout findable, and it has
        to be on *that step*. A step running this module without it skips
        exactly as before, with a green tick to show for it.

        The first version of this test asserted the variable appeared anywhere
        in the `gauntlet` job, and the job's other step already sets it -- so
        deleting the variable from the new step left the test green. Found by
        breaking it on purpose, which is the only way that kind of hole is
        ever found.
        """
        steps = self.gauntlet_job_steps()
        running = [
            step for step in steps if "tests.test_gauntlet_interlock" in step
        ]
        self.assertEqual(
            len(running), 1, "exactly one step should run the interlock suite"
        )
        self.assertIn(
            "GAUNTLET_CHECKOUT",
            running[0],
            "the step that runs the suite does not name the checkout, so "
            "TestTheFullGate skips inside it and the run is green anyway:\n"
            + running[0],
        )

    def gauntlet_job_steps(self) -> list[str]:
        """The `gauntlet` job's steps, one string each."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        split = workflow.split("\n  gauntlet:\n", 1)
        self.assertEqual(len(split), 2, "no `gauntlet:` job in ci.yml")
        body = split[1]
        # A job ends where the next two-space key begins.
        for index, line in enumerate(body.splitlines()):
            if re.match(r"^  [a-z][\w-]*:\s*$", line):
                body = "\n".join(body.splitlines()[:index])
                break
        steps: list[str] = []
        current: list[str] = []
        for line in body.splitlines():
            if re.match(r"^      - (name|uses):", line):
                if current:
                    steps.append("\n".join(current))
                current = [line]
            elif current:
                current.append(line)
        if current:
            steps.append("\n".join(current))
        return steps


if __name__ == "__main__":
    unittest.main()
