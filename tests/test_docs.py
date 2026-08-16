"""R7: the walkthrough says what happens, and what happens matches it.

Drift between documentation and behavior is a defect class, so it gets a test
rather than a promise. Every ``console`` block in ``docs/demo.md`` that starts
with a ``cairn`` command is executed here — in a temporary directory holding
nothing but the shipped configuration and corpus, so the run is the clean
checkout the page claims — and its recorded output must match byte for byte.

Blocks fenced as ``text`` rather than ``console`` are not run: ``cairn serve``
does not return, and a page that pretended otherwise would be its own kind of
drift.

The README is executed too, under a looser rule, because it was drifting while
the walkthrough could not. Its blocks are illustrative: hard-wrapped for a
column of prose and elided with ``...`` where the real output runs long, so
they cannot be compared byte for byte. What they can be held to is that every
word they *do* show is a word the command actually printed, in that order —
see :class:`TestTheReadmeShowsRealOutput` for what that caught.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_PAGE = ROOT / "docs" / "demo.md"
README = ROOT / "README.md"

CONSOLE_BLOCK = re.compile(r"```console\n(.*?)```", re.DOTALL)


def documented_runs():
    """(command, expected output) for every runnable block on the page."""
    runs = []
    for block in CONSOLE_BLOCK.findall(DEMO_PAGE.read_text(encoding="utf-8")):
        lines = block.split("\n")
        if not lines[0].startswith("$ "):
            continue
        command = lines[0][2:]
        if not command.startswith("python3 -m cairn"):
            continue  # orientation only (the clone and cd lines)
        # A block may hold several commands with no output between them.
        expected = []
        for line in lines[1:]:
            if line.startswith("$ "):
                runs.append((command, "\n".join(expected).rstrip("\n")))
                command, expected = line[2:], []
                if not command.startswith("python3 -m cairn"):
                    break
            else:
                expected.append(line)
        runs.append((command, "\n".join(expected).rstrip("\n")))
    return runs


class CleanCheckout(unittest.TestCase):
    """A workspace holding nothing but the shipped config and corpus."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        workspace = Path(cls._tmp.name)
        shutil.copy(ROOT / "cairn.toml", workspace / "cairn.toml")
        shutil.copytree(ROOT / "corpus", workspace / "corpus")
        cls.workspace = workspace
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_documented(self, command: str) -> subprocess.CompletedProcess:
        # The page writes `python3`; run the interpreter the suite is running
        # under, so a checkout tested on 3.11 is not silently tested on
        # something else.
        completed = subprocess.run(
            command.replace("python3 ", f"{sys.executable} ", 1),
            shell=True, cwd=self.workspace, env=self.env,
            capture_output=True, text=True,
        )
        self.assertEqual(
            completed.returncode, 0,
            f"{command} exited {completed.returncode}: {completed.stderr}",
        )
        return completed


class TestDemoPage(CleanCheckout):
    def test_the_page_actually_documents_the_demo(self):
        runs = documented_runs()
        self.assertGreaterEqual(len(runs), 6, "the walkthrough should walk somewhere")
        commands = [command for command, _ in runs]
        self.assertTrue(commands[0].endswith("cairn index"), "the demo starts by indexing")
        self.assertTrue(any("--explain" in c for c in commands), "explain mode is shown")
        self.assertTrue(any("--lang" in c for c in commands), "language selection is shown")

    def test_every_documented_command_produces_its_documented_output(self):
        for command, expected in documented_runs():
            with self.subTest(command=command):
                completed = self.run_documented(command)
                self.assertEqual(
                    completed.stdout.rstrip("\n"),
                    expected,
                    f"docs/demo.md is out of date for: {command}",
                )

    def test_the_readme_points_at_this_page_as_the_executed_one(self):
        self.assertIn("executed by the test suite", README.read_text(encoding="utf-8"))

    def test_the_serve_block_is_not_claimed_to_be_reproducible(self):
        page = DEMO_PAGE.read_text(encoding="utf-8")
        serve_blocks = [b for b in CONSOLE_BLOCK.findall(page) if "cairn serve" in b]
        self.assertEqual(serve_blocks, [], "a command that never returns cannot be checked")
        self.assertIn("cairn serve", page, "...but it must still be documented")


# Elisions. A line that is only dots means "output continues, resume matching
# after this"; a line ending in dots means the same thing mid-line. Both
# collapse to the same marker once whitespace is normalized.
ELISION = "..."

# Unicode bidirectional isolates, stripped before matching. They wrap Latin
# runs inside right-to-left output and are invisible on screen; requiring
# prose documentation to carry invisible control characters would make it
# unmaintainable, and `tests/test_multilingual.py` is where the isolating is
# actually pinned.
INVISIBLE = str.maketrans({"⁨": None, "⁩": None, "⁦": None, "⁧": None})

README_SUBCOMMANDS = ("index", "ask")


def readme_runs() -> list[tuple[str, str]]:
    """(command, shown output) for the README blocks that can be run.

    `serve` never returns and `record` writes the evidence bundle, so only
    `index` and `ask` are executed; the blocks that show the gate, the guard
    and the browser checks are not this file's business.
    """
    runs: list[tuple[str, str]] = []
    for block in CONSOLE_BLOCK.findall(README.read_text(encoding="utf-8")):
        command, shown = None, []
        for line in block.split("\n"):
            if line.startswith("$ "):
                if command is not None:
                    runs.append((command, "\n".join(shown)))
                command, shown = line[2:], []
            elif command is not None:
                shown.append(line)
        if command is not None:
            runs.append((command, "\n".join(shown)))
    return [
        (command, shown)
        for command, shown in runs
        if command.split()[:3] == ["python3", "-m", "cairn"]
        and len(command.split()) > 3
        and command.split()[3] in README_SUBCOMMANDS
    ]


class TestTheReadmeShowsRealOutput(CleanCheckout):
    """Every word the README shows is a word the command printed.

    Not byte for byte: these blocks are hard-wrapped to fit a column of prose
    and elided with `...` where the output runs long, so an exact comparison
    would fail on formatting rather than on truth. What is required instead is
    that each stretch of shown output, with whitespace collapsed, appears in
    the real output, and that the stretches appear in the order shown.

    This is here because the README was wrong in two ways at once and nothing
    was checking. `retrieval.max_passages` went from 2 to 1 after an audit
    finding, and the quick-start block kept showing a two-source answer to a
    question that now cites one. And the English refusal in it was the wording
    from before the audit — the one that said it had no source without saying
    it could not help, which this project records as a defect it fixed.
    """

    def fragments(self, shown: str) -> list[str]:
        return [
            part for part in (
                " ".join(chunk.split()) for chunk in shown.split(ELISION)
            ) if part
        ]

    def test_there_are_blocks_to_check(self):
        # The filter above is a list of subcommand names. If a rename made it
        # match nothing, every check below would pass over an empty list.
        runs = readme_runs()
        self.assertGreaterEqual(len(runs), 5, [c for c, _ in runs])
        self.assertTrue(any("--explain" in c for c, _ in runs))
        self.assertTrue(any("--lang" in c for c, _ in runs))

    def test_every_shown_line_is_a_line_the_command_printed(self):
        for command, shown in readme_runs():
            with self.subTest(command=command):
                actual = " ".join(
                    self.run_documented(command).stdout.translate(INVISIBLE).split()
                )
                position = 0
                for fragment in self.fragments(shown):
                    found = actual.find(fragment, position)
                    self.assertNotEqual(
                        found, -1,
                        f"README.md shows output `{command}` does not produce:\n"
                        f"  shown:  {fragment}\n"
                        f"  actual: {actual[position:position + 240]}",
                    )
                    position = found + len(fragment)


if __name__ == "__main__":
    unittest.main()
