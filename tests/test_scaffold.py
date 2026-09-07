"""`cairn init`: what it writes, what it refuses, and what it leaves undone.

The verb's whole claim is that an agency installing Cairn from PyPI gets the
audit interlock too, and that the parts nobody can scaffold arrive *refusing*
rather than filled in with something plausible. Both halves are tested here:
the files exist and work, and the three deliberately unfinished ones stop the
commands that would otherwise present a green gate nobody earned.

The other job of this file is holding the shipped templates to the repository
files they are copies of. A packaged copy that drifts is a second, older gate,
and a packaged pin that drifts is a pin that stops meaning anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from cairn import __version__
from cairn.config import Config, load_config
from cairn.record import RecordError, load_questions
from cairn.scaffold import (
    EXECUTABLE,
    PLACEHOLDERS,
    SUITES,
    ScaffoldError,
    draft_questions,
    init,
    render,
    template,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"


class ScaffoldHarness(unittest.TestCase):
    def scaffold(self, corpus: Path | None = None, name: str | None = None) -> Path:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())) / "deployment"
        init(directory, corpus or DEMO, name=name)
        return directory


# --------------------------------------------------------------------------
# The templates are copies, and copies drift


class TestTheShippedCopiesAreTheRepositoryFiles(unittest.TestCase):
    """A packaged copy that drifts is a second, older gate.

    These files cannot be read from the repository at run time — a deployment
    scaffolded from a wheel has the package and nothing else — so they ship
    inside it, and equality is what makes that safe rather than a liability.
    """

    COPIES = (
        ("plumbline-gate.sh", "plumbline-gate.sh"),
        ("gauntlet-gate.sh", "gauntlet-gate.sh"),
        ("plumbline.pin", "plumbline.pin"),
        ("gauntlet.pin", "gauntlet.pin"),
    )

    def test_every_copy_is_byte_equal_to_its_original(self):
        for packaged, original in self.COPIES:
            with self.subTest(file=packaged):
                self.assertEqual(
                    template(packaged),
                    (ROOT / original).read_text(encoding="utf-8"),
                )

    def test_the_suite_list_is_the_one_the_target_file_declares(self):
        """`SUITES` is a hand-held list because there is no repository at run
        time. This is the other half: a suite the harness has added and the
        list does not name is a suite nobody would be graded on."""
        target = tomllib.loads(
            (ROOT / "plumbline" / "target.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(target["suites"]), SUITES)


# --------------------------------------------------------------------------
# Rendering


class TestRendering(unittest.TestCase):
    def test_a_placeholder_left_behind_is_refused(self):
        """A template still saying `{{NAME}}` would ship the template's own
        words as though they were the operator's."""
        with self.assertRaises(ScaffoldError):
            render("hello {{NAME}}")

    def test_a_github_expression_is_not_a_placeholder(self):
        """`audit.yml` is full of `${{ github.ref }}`. A generic sweep for
        `{{` would refuse to render the workflow at all."""
        body = render("group: ${{ github.workflow }}-{{NAME}}", NAME="x")
        self.assertEqual(body, "group: ${{ github.workflow }}-x")

    def test_the_workflow_template_renders(self):
        rendered = render(template("audit.yml"), VERSION=__version__)
        self.assertIn(f'cairn-assistant=={__version__}', rendered)
        self.assertIn("${{ github.ref }}", rendered)

    def test_every_template_that_carries_a_placeholder_is_rendered_by_init(self):
        """A template with an unsubstituted placeholder would fail `render`
        at scaffold time, which is the point; this checks the set of tokens
        the module declares is the set the templates actually use."""
        used = set()
        for name in ("cairn.toml", "README.md", "target.toml", "audit.yml"):
            body = template(name)
            used.update(token for token in PLACEHOLDERS if token in body)
        self.assertEqual(used, set(PLACEHOLDERS))


# --------------------------------------------------------------------------
# What init writes


class TestWhatItWrites(ScaffoldHarness):
    def test_it_writes_every_file_the_interlock_needs(self):
        directory = self.scaffold()
        for name in (
            "cairn.toml",
            "questions.toml",
            "README.md",
            "plumbline.pin",
            "gauntlet.pin",
            "plumbline/target.toml",
            "plumbline/baseline.json",
            "plumbline-gate.sh",
            "gauntlet-gate.sh",
            ".github/workflows/audit.yml",
        ):
            with self.subTest(file=name):
                self.assertTrue((directory / name).is_file(), name)

    def test_the_gate_scripts_are_executable(self):
        directory = self.scaffold()
        for name in EXECUTABLE:
            with self.subTest(file=name):
                self.assertTrue(os.access(directory / name, os.X_OK), name)

    def test_it_is_deterministic(self):
        first, second = self.scaffold(), self.scaffold()
        for name in ("cairn.toml", "questions.toml", "plumbline/target.toml"):
            with self.subTest(file=name):
                self.assertEqual(
                    (first / name).read_text(encoding="utf-8").replace(
                        first.name, "D"
                    ),
                    (second / name).read_text(encoding="utf-8").replace(
                        second.name, "D"
                    ),
                )

    def test_the_scaffolded_config_loads_and_names_the_corpus(self):
        directory = self.scaffold()
        cfg = load_config(directory / "cairn.toml")
        self.assertEqual(Path(cfg.corpus_path).resolve(), DEMO.resolve())

    def test_the_target_file_sets_no_floor_anywhere(self):
        """Every suite takes the pinned harness's own default. A scaffold that
        guessed floors would be guessing what is good enough for the people
        this deployment serves."""
        target = tomllib.loads(
            (self.scaffold() / "plumbline" / "target.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(target["suites"]), SUITES)
        for name, suite in target["suites"].items():
            with self.subTest(suite=name):
                self.assertTrue(suite["enabled"])
                self.assertNotIn("floor", suite)

    def test_a_corpus_inside_the_deployment_is_named_relatively(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())) / "d"
        corpus = directory / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "a.md").write_text(
            "---\nid: a\ntitle: A\nlang: en\n---\n\nBody text.\n", encoding="utf-8"
        )
        init(directory, corpus)
        self.assertIn('path = "corpus"', (directory / "cairn.toml").read_text("utf-8"))

    def test_a_corpus_outside_it_is_named_absolutely(self):
        """`../../../elsewhere/corpus` breaks the moment the directory is
        moved, and a deployment directory is a thing people move."""
        body = (self.scaffold() / "cairn.toml").read_text(encoding="utf-8")
        self.assertIn(f'path = "{DEMO.resolve().as_posix()}"', body)


class TestWhatItRefuses(ScaffoldHarness):
    def test_running_it_twice_refuses_and_writes_nothing(self):
        directory = self.scaffold()
        marker = (directory / "cairn.toml").read_bytes()
        with self.assertRaises(ScaffoldError) as caught:
            init(directory, DEMO)
        self.assertIn("already holds", str(caught.exception))
        self.assertEqual((directory / "cairn.toml").read_bytes(), marker)

    def test_one_existing_file_is_enough_to_refuse(self):
        """Partial output is worse than none: a half-scaffolded directory
        looks finished, and the file it did not overwrite is the one somebody
        had already customised."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())) / "d"
        directory.mkdir()
        (directory / "README.md").write_text("mine", encoding="utf-8")
        with self.assertRaises(ScaffoldError):
            init(directory, DEMO)
        self.assertEqual((directory / "README.md").read_text(encoding="utf-8"), "mine")
        self.assertFalse((directory / "cairn.toml").exists())

    def test_a_corpus_that_is_not_there_refuses(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())) / "d"
        with self.assertRaises(ScaffoldError):
            init(directory, directory / "nope")

    def test_a_corpus_that_cannot_be_read_refuses_before_writing(self):
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        corpus = workspace / "corpus"
        corpus.mkdir()
        (corpus / "broken.md").write_text("no front matter here\n", encoding="utf-8")
        directory = workspace / "d"
        with self.assertRaises(ScaffoldError):
            init(directory, corpus)
        self.assertFalse(directory.exists())


# --------------------------------------------------------------------------
# The three things left undone, each refusing


class TestTheUnfinishedPartsRefuse(ScaffoldHarness):
    """Not gaps. Each is a decision only a person who has read the corpus can
    make, and each arrives refusing rather than filled in with something
    plausible, because a plausible one is a green gate nobody earned."""

    def test_the_drafted_question_set_is_refused_by_record(self):
        directory = self.scaffold()
        with self.assertRaises(RecordError):
            load_questions(directory / "questions.toml")

    def test_it_drafts_one_item_per_document(self):
        body, count = draft_questions(DEMO)
        self.assertEqual(count, len(tomllib.loads(body)["item"]))
        self.assertEqual(count, 11)

    def test_every_drafted_item_is_blank_and_marked_a_draft(self):
        items = tomllib.loads(draft_questions(DEMO)[0])["item"]
        self.assertTrue(items)
        for item in items:
            with self.subTest(item=item["id"]):
                self.assertEqual(item["prompt"], "")
                self.assertEqual(item["answering_sources"], [])
                self.assertEqual(item["review"], "draft")

    def test_the_scaffolded_contact_is_blank_and_serve_refuses_it(self):
        cfg = load_config(self.scaffold() / "cairn.toml")
        self.assertEqual(cfg.contact, "")
        self.assertEqual(cfg.unserveable_contacts(), ("",))

    def test_the_baseline_is_a_placeholder_that_says_so(self):
        baseline = json.loads(
            (self.scaffold() / "plumbline" / "baseline.json").read_text(encoding="utf-8")
        )
        self.assertEqual(baseline["verdict"], "PLACEHOLDER")
        self.assertEqual(baseline["suites"], [])
        self.assertIn("placeholder", " ".join(baseline["_comment"]).lower())

    def test_the_readme_names_all_three(self):
        readme = (self.scaffold() / "README.md").read_text(encoding="utf-8")
        for phrase in ("contact", "questions.toml", "baseline.json", "audit_guard.py"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)


class TestTheServeRefusal(unittest.TestCase):
    """`serve` is the verb that puts this in front of the public, so it is the
    verb that asks whether the refusal points at a real person."""

    def test_a_blank_contact_is_unserveable(self):
        cfg = Config(contact="", contact_by_language={})
        self.assertEqual(cfg.unserveable_contacts(), ("",))

    def test_whitespace_is_not_a_contact(self):
        self.assertEqual(
            Config(contact="   ", contact_by_language={}).unserveable_contacts(), ("",)
        )

    def test_the_shipped_demo_contact_is_unserveable(self):
        """A phone number that does not exist, attached to a county that does
        not exist, said with the same confidence as a real one."""
        self.assertIn("", Config().unserveable_contacts())

    def test_a_real_contact_serves(self):
        cfg = Config(
            contact="the county benefits line on 555-0100",
            contact_by_language={"en": "the county benefits line on 555-0100"},
        )
        self.assertEqual(cfg.unserveable_contacts(), ())

    def test_one_bad_language_is_named_even_when_the_default_is_real(self):
        cfg = Config(
            contact="the county benefits line on 555-0100",
            contact_by_language={"en": "the county benefits line on 555-0100", "es": ""},
        )
        self.assertEqual(cfg.unserveable_contacts(), ("es",))


# --------------------------------------------------------------------------
# End to end


class TestAScaffoldedDeploymentWorks(ScaffoldHarness):
    """The claim `init` makes is that the result runs, not that the files
    exist. Run through the real CLI in the scaffolded directory."""

    def run_cairn(self, directory: Path, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "cairn", "--config", "cairn.toml", *argv],
            cwd=directory,
            env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def test_index_then_ask_works_in_a_fresh_directory(self):
        directory = self.scaffold()
        indexed = self.run_cairn(directory, "index")
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        asked = self.run_cairn(
            directory, "ask", "How much is the monthly grocery allowance for one person?"
        )
        self.assertEqual(asked.returncode, 0, asked.stderr)
        self.assertIn("$212 per month", asked.stdout)

    def test_serve_refuses_the_blank_contact(self):
        directory = self.scaffold()
        self.assertEqual(self.run_cairn(directory, "index").returncode, 0)
        served = self.run_cairn(directory, "serve", "--port", "0")
        self.assertEqual(served.returncode, 1, served.stdout)
        self.assertIn("[refusal] contact", served.stderr)
        self.assertEqual(served.stdout, "", "nothing was served")

    def test_record_refuses_the_drafted_question_set(self):
        directory = self.scaffold()
        self.assertEqual(self.run_cairn(directory, "index").returncode, 0)
        recorded = self.run_cairn(
            directory, "record", "--questions", "questions.toml", "--out", "bundle"
        )
        self.assertEqual(recorded.returncode, 1, recorded.stdout)
        self.assertFalse((directory / "bundle" / "items.jsonl").exists())


class TestTheConfigDoesNotLeakIn(ScaffoldHarness):
    def test_init_ignores_the_ambient_configuration(self):
        """Every other verb runs *against* a configuration; this one writes
        the first. Run from a checkout of this repository, reading the ambient
        `cairn.toml` would hand a new deployment the fictional demo contact,
        which is the one value it must not start with."""
        directory = self.scaffold()
        body = (directory / "cairn.toml").read_text(encoding="utf-8")
        self.assertNotIn("555-0142", body)
        self.assertNotIn("Harbor County", body)


if __name__ == "__main__":
    unittest.main()
