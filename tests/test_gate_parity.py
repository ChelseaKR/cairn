"""`make verify` and CI's `core` job must run the same list.

The hole this closes was open for the whole life of the repository, and the
Makefile's own header described it as impossible:

    # The development gate, in one place, so that "what CI runs" and "what a
    # contributor runs" cannot be two different lists that drift apart. CI's
    # `core` job calls these targets rather than repeating their commands.

`core` did not call the targets. It repeated two of the four -- `ruff check .`
and a bare `python3 -m unittest discover -s tests` -- and that was the whole
job. Three checks were therefore local-only:

- **`mypy`.** A type error `make verify` fails on passed `core` cleanly. Tried
  on this tree: an `int` returned from a function annotated `-> str` in
  `cairn/coverage.py` gave `mypy` one error and gave `ruff check .` and
  `unittest discover` exit 0 apiece.
- **`coverage report`, and with it `fail_under = 85`.** `core` never ran
  `coverage` at all -- `grep -c coverage .github/workflows/*` was 0 -- so the
  floor was a number in `pyproject.toml` that no CI job could breach.
- **`uv lock --check`.** `core` installs with pip and never reads `uv.lock`, so
  a lockfile that stopped agreeing with `pyproject.toml` broke `make install`
  for every contributor with nothing red anywhere.

None of that was hidden by a skip or a swallowed exit code. It was a shorter
list, in a second file, with a sentence in the first file saying the two lists
were the same one. That is the failure this repository names as its own worst
case: a gate that is present, green, and structurally incapable of reporting
what it exists to report.

So the sentence is checked now. This file parses both files -- with small
parsers rather than a YAML or Make dependency, the same choice
`tests/test_rulesets.py` makes and for the same reason -- and holds every
command `make verify` runs against the commands `core` runs.

**The one permitted difference is `$(UVRUN)`.** Every Makefile recipe runs
through `uv run --locked --extra dev`, which pins a single interpreter;
`core`'s entire purpose is the Python matrix, so it invokes the pip-installed
tool directly. The comparison strips that prefix and allows nothing else.

Scoped to `core`. The Windows and macOS legs are OS canaries running the
install/lint/test path at one Python version, and they say so; holding them to
this list too would make them a third and fourth full gate rather than the
"does this also work here" they are documented as. They live in
`os-canary.yml` on a nightly schedule (CI-CD-STANDARD.md §11b), not in this
workflow, so the scope check below reads that file.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
OS_CANARY = ROOT / ".github" / "workflows" / "os-canary.yml"

# `UVRUN := uv run --locked --extra dev` in the Makefile. The prefix is the
# difference between the two gates that is allowed; see the module docstring.
UVRUN_ASSIGNMENT = re.compile(r"^UVRUN\s*:?=\s*(.+?)\s*$", re.MULTILINE)

# A make target line: `name: prereq prereq`. Recipes are the tab-indented
# lines under it.
TARGET = re.compile(r"^([a-z][\w-]*):\s*(.*?)\s*$")


def uvrun_prefix(text: str) -> str:
    found = UVRUN_ASSIGNMENT.search(text)
    if found is None:  # pragma: no cover - a Makefile without it is a failure
        raise AssertionError("the Makefile no longer defines UVRUN")
    return found.group(1)


def make_targets(text: str) -> dict[str, tuple[list[str], list[str]]]:
    """`{target: (prerequisites, recipe lines)}` for every target."""
    targets: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None:
                command = line.lstrip("\t").strip()
                # `@echo` and friends: the leading modifier is not part of the
                # command, and a recipe line that only echoes is not a check.
                if command:
                    targets[current][1].append(command)
            continue
        if line.startswith("#") or not line.strip():
            continue
        found = TARGET.match(line)
        if found and not line.startswith(".PHONY"):
            name = found.group(1)
            prerequisites = found.group(2).split()
            targets[name] = (prerequisites, [])
            current = name
            continue
        current = None
    return targets


def verify_commands(text: str) -> list[str]:
    """Every command `make verify` runs, in order, with `$(UVRUN)` resolved
    away.

    `verify`'s own recipe is skipped only where it is a bare `@echo`: printing
    "verify: ok" is not a check and has no CI counterpart.
    """
    targets = make_targets(text)
    prefix = uvrun_prefix(text)
    commands: list[str] = []
    for prerequisite in targets["verify"][0]:
        for command in targets[prerequisite][1]:
            resolved = command.replace("$(UVRUN)", prefix).strip()
            # Strip the prefix itself: CI runs the pip-installed tool.
            if resolved.startswith(prefix):
                resolved = resolved[len(prefix) :].strip()
            commands.append(resolved)
    for command in targets["verify"][1]:
        if command.startswith("@echo"):
            continue
        commands.append(command)  # pragma: no cover - none today
    return commands


def _job_lines(text: str, job: str) -> list[str]:
    """The raw lines belonging to one job under `jobs:`, in order."""
    lines: list[str] = []
    in_jobs = False
    in_job = False
    for raw in text.splitlines():
        if raw.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if re.match(r"^  [a-z][\w-]*:\s*$", raw.rstrip()):
            in_job = raw.strip().rstrip(":") == job
            continue
        if in_job:
            lines.append(raw)
    return lines


def _is_command(line: str) -> bool:
    """A comment is not a command.

    Without this, `# mypy` inside a `run: |` block satisfied the parity check
    below -- this file's own version of the defect it exists to catch, and it
    was there until `test_a_commented_out_command_does_not_count` was written.
    """
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def job_run_commands(text: str, job: str) -> list[str]:
    """Every shell command in a job's `run:` steps, in order.

    A small parser rather than a YAML dependency, matching
    `tests/test_rulesets.py`'s reasoning: the core dev path is standard-library
    only, and this reads a file we own.
    """
    commands: list[str] = []
    block_indent: int | None = None
    for raw in _job_lines(text, job):
        line = raw.rstrip()
        if block_indent is not None:
            indent = len(raw) - len(raw.lstrip())
            if line.strip() and indent >= block_indent:
                if _is_command(raw):
                    commands.append(raw.strip())
                continue
            block_indent = None
        opened = re.match(r"^(\s*)run:\s*\|\s*$", line)
        if opened:
            block_indent = len(opened.group(1)) + 2
            continue
        inline = re.match(r"^\s*run:\s*(\S.*)$", line)
        if inline:
            commands.append(inline.group(1).strip())
    return commands


class TestTheTwoGatesRunTheSameList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.makefile = MAKEFILE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.os_canary = OS_CANARY.read_text(encoding="utf-8")

    def test_every_make_verify_command_runs_in_ci(self):
        wanted = verify_commands(self.makefile)
        ran = job_run_commands(self.workflow, "core")
        missing = [command for command in wanted if command not in ran]
        self.assertEqual(
            missing,
            [],
            "`make verify` runs a check CI's `core` job does not. A check that "
            "only a contributor's laptop can fail is not a gate. Add the step "
            "to the `core` job in .github/workflows/ci.yml, or, if it genuinely "
            "cannot run there, say so here with the reason rather than deleting "
            "this assertion.",
        )

    def test_the_parse_found_a_real_list(self):
        """A parser that returned nothing would make the test above pass by
        comparing two empty lists -- which is the exact failure mode this file
        exists to catch, one level up.
        """
        wanted = verify_commands(self.makefile)
        self.assertGreaterEqual(len(wanted), 4, wanted)
        self.assertIn("ruff check .", wanted)
        self.assertIn("mypy", wanted)
        self.assertIn("uv lock --check", wanted)
        self.assertTrue(
            any(command.startswith("coverage report") for command in wanted), wanted
        )
        ran = job_run_commands(self.workflow, "core")
        self.assertGreaterEqual(len(ran), 8, ran)
        self.assertIn("ruff check .", ran)

    def test_the_coverage_floor_is_reached_through_coverage_report(self):
        """`fail_under` is enforced by `coverage report` and by nothing else.
        A `core` job that ran `coverage run` and skipped the report would
        collect the data and never compare it to the floor.
        """
        ran = job_run_commands(self.workflow, "core")
        self.assertIn("coverage report", ran)
        self.assertIn("coverage run -m unittest discover -s tests", ran)
        self.assertNotIn(
            "python3 -m unittest discover -s tests",
            ran,
            "the bare test run is back beside the coverage one; the floor is "
            "then satisfiable by the run that does not check it",
        )
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("fail_under", pyproject)

    def test_the_makefile_header_points_at_what_checks_it(self):
        """The header's claim about CI is the thing that made the gap
        invisible for the whole life of the repository: it was believed, and
        nothing read it. It now names this file, so shortening the header back
        to an unchecked assertion has to go through a failing test rather than
        through a tidy-up.

        Deliberately not a check for the absence of the old sentence -- the
        header quotes it, in the past tense, as the record of what was wrong.
        Substring-matching prose is how a test starts failing for editorial
        reasons; what is worth holding is the pointer.
        """
        self.assertIn("test_gate_parity.py", self.makefile)
        self.assertIn("cannot be two different lists that drift apart", self.makefile)

    def test_a_commented_out_command_does_not_count(self):
        """The parser's own hole, closed. A required command that appears only
        as a comment in a `run: |` block would otherwise satisfy the parity
        check -- a check made green by text that never executes, which is the
        exact shape this file exists to catch one level up.
        """
        workflow = (
            "jobs:\n"
            "  core:\n"
            "    steps:\n"
            "      - name: Test\n"
            "        run: |\n"
            "          # mypy\n"
            "          echo hello\n"
        )
        self.assertEqual(job_run_commands(workflow, "core"), ["echo hello"])

    def test_the_os_canaries_are_still_only_canaries(self):
        """Scope, asserted rather than left to a comment. The Windows and macOS
        legs are not held to the full list, and the reason is that they are
        documented as one-version canaries. If either ever grows the full gate,
        this is the test that should be rewritten to say so.

        They are one matrixed `core-os` job in `os-canary.yml` now rather than
        two jobs here, so this reads that file. The assertion is unchanged:
        the canary still actually runs something, and that something includes
        the lint step.
        """
        ran = job_run_commands(self.os_canary, "core-os")
        self.assertTrue(ran, "core-os has no run steps at all")
        self.assertIn("ruff check .", ran)

    def test_the_os_canaries_are_not_on_per_push_ci(self):
        """CI-CD-STANDARD.md §11b: macOS is 10x minutes and Windows is 2x, and
        neither belongs on per-push CI. A canary that quietly moves back into
        `ci.yml` costs that multiple on every commit, so pin it here.
        """
        self.assertNotIn("macos-latest", self.workflow)
        self.assertNotIn("windows-latest", self.workflow)
        self.assertIn("macos-latest", self.os_canary)
        self.assertIn("windows-latest", self.os_canary)
        self.assertIn("schedule:", self.os_canary)


if __name__ == "__main__":
    unittest.main()
