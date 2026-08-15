"""R7: the walkthrough says what happens, and what happens matches it.

Drift between documentation and behavior is a defect class, so it gets a test
rather than a promise. Every ``console`` block in ``docs/demo.md`` that starts
with a ``cairn`` command is executed here — in a temporary directory holding
nothing but the shipped configuration and corpus, so the run is the clean
checkout the page claims — and its recorded output must match byte for byte.

Blocks fenced as ``text`` rather than ``console`` are not run: ``cairn serve``
does not return, and a page that pretended otherwise would be its own kind of
drift.
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


class TestDemoPage(unittest.TestCase):
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
                # The page writes `python3`; run the interpreter the suite is
                # running under, so a checkout tested on 3.11 is not silently
                # tested on something else.
                runnable = command.replace("python3 ", f"{sys.executable} ", 1)
                completed = subprocess.run(
                    runnable,
                    shell=True,
                    cwd=self.workspace,
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{command} exited {completed.returncode}: {completed.stderr}",
                )
                self.assertEqual(
                    completed.stdout.rstrip("\n"),
                    expected,
                    f"docs/demo.md is out of date for: {command}",
                )

    def test_the_serve_block_is_not_claimed_to_be_reproducible(self):
        page = DEMO_PAGE.read_text(encoding="utf-8")
        serve_blocks = [b for b in CONSOLE_BLOCK.findall(page) if "cairn serve" in b]
        self.assertEqual(serve_blocks, [], "a command that never returns cannot be checked")
        self.assertIn("cairn serve", page, "...but it must still be documented")


if __name__ == "__main__":
    unittest.main()
