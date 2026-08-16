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


class TestTheAuditFiguresInTheDocuments(unittest.TestCase):
    """The audit transcripts are in unexecuted fences, so they need their own.

    `README.md` and `docs/demo.md` both show a gate block. Neither is run:
    `readme_runs()` keeps only `index` and `ask`, and the demo page's audit
    section is fenced as ```text because it needs the network the first time.
    So the figures in them were being maintained by hand, and one of them
    rotted — the README carried run id `958f5afd…`, from before `plumbline.pin`
    last regenerated the baseline. The run id is a hash of the evidence, the
    judge configuration, the floors *and* the baseline, and nothing offline can
    recompute it, so it is elided in both pages now.

    The dataset id can be checked: it is the first twelve characters of the
    bundle's own SHA-256, which this repository writes. So it is, here.

    `DESIGN.md` is deliberately not in scope. Its two remaining literal ids
    are inside the tamper drills — captured from a deliberately broken tree
    (threshold 0.105) and from a deliberately stale baseline — so they are
    records of a run that is *not* the committed one, and holding them to the
    committed bundle would be requiring them to be the thing they exist to
    differ from. Both were re-executed on 2026-08-16 rather than re-typed.
    """

    DOCUMENTS = ("README.md", "docs/demo.md")
    DATASET_ID = re.compile(r"dataset ([0-9a-f]{6,})")
    RUN_ID = re.compile(r"run ([0-9a-f]{6,})")

    def setUp(self):
        import json

        checksums = json.loads(
            (ROOT / "plumbline" / "bundle" / "checksums.json").read_text(encoding="utf-8")
        )
        self.bundle_sha256 = checksums["bundle_sha256"]

    def test_every_dataset_id_shown_is_the_committed_bundle_s(self):
        seen = 0
        for name in self.DOCUMENTS:
            text = (ROOT / name).read_text(encoding="utf-8")
            for shown in self.DATASET_ID.findall(text):
                seen += 1
                with self.subTest(document=name, dataset=shown):
                    self.assertTrue(
                        self.bundle_sha256.startswith(shown),
                        f"{name} shows dataset {shown}, but the committed bundle "
                        f"hashes to {self.bundle_sha256[:12]}",
                    )
        self.assertGreaterEqual(seen, 2, "no document shows a dataset id any more")

    def test_the_published_test_count_is_the_count(self):
        # "307 tests plus 63 browser behaviour checks" is a claim about
        # coverage, sitting in the second paragraph of the README, and nothing
        # held it. It was updated by hand each time somebody remembered, which
        # means a commit that deletes forty tests can leave the sentence
        # standing and read as a commit that deleted nothing.
        #
        # Discovered, not run: `countTestCases` walks the suite the loader
        # built and never executes it, so this does not recurse.
        import unittest as ut

        discovered = ut.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        self.assertEqual(discovered.countTestCases(), self.published_count("tests"))

    def test_the_published_browser_check_count_is_the_one_a11y_pins(self):
        # The browser checks do not run in this path — no Node, no Chromium,
        # by design — so what is checkable here is that the README and
        # a11y.mjs agree. a11y.mjs holds itself to the number at run time and
        # exits non-zero if fewer checks ran, which is the half of the claim
        # that needs a browser.
        script = (ROOT / "tests" / "browser" / "a11y.mjs").read_text(encoding="utf-8")
        pinned = re.search(r"const EXPECTED_CHECKS = (\d+);", script)
        self.assertIsNotNone(pinned, "a11y.mjs no longer pins how many checks it runs")
        self.assertEqual(int(pinned.group(1)), self.published_count("browser behaviour checks"))
        self.assertIn(f"{pinned.group(1)}/{pinned.group(1)} behaviour checks passed",
                      (ROOT / "README.md").read_text(encoding="utf-8"))

    def published_count(self, phrase: str) -> int:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        found = re.search(rf"(\d+) {re.escape(phrase)}", text)
        self.assertIsNotNone(found, f"the README no longer publishes a {phrase} count")
        return int(found.group(1))

    def test_no_document_publishes_a_run_id_nothing_can_check(self):
        # A run id is derived from four inputs and cannot be recomputed without
        # the harness, so a literal one here is a number with no check under it
        # — which is how the last one went stale.
        for name in self.DOCUMENTS:
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(document=name):
                self.assertEqual(
                    self.RUN_ID.findall(text), [],
                    "elide the run id (`run ...`): nothing offline can verify it",
                )


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
