"""The gauntlet interlock, checked offline.

The full gate needs a checkout of the pinned harness and is CI's job. What
the core dev path can hold without it — and therefore what these tests hold —
is the same discipline tests/test_interlock.py applies to the audit side:
the pin says exactly one thing, the suites are structurally sound, the gate
fails closed when its harness cannot be resolved, and nothing here can drift
from those facts quietly.
"""

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
    (ROOT.parent / "gauntlet" / ".git").is_dir(), "no local gauntlet checkout"
)
@unittest.skipIf(
    sys.platform == "win32",
    "gauntlet-gate.sh needs a shell to exec its shebang; see "
    "TestTheGateFailsClosed's skip reason above.",
)
class TestTheFullGate(unittest.TestCase):
    """Runs only where a sibling checkout exists; CI runs it always."""

    def test_the_gate_passes_against_the_local_pinned_checkout(self):
        head = subprocess.run(
            ["git", "-C", str(ROOT.parent / "gauntlet"), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head != SHA256_RE.search(PIN.read_text(encoding="utf-8")).group(1):
            self.skipTest("sibling checkout is not at the pinned commit")
        completed = subprocess.run(
            [str(GATE)], capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("overall: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
