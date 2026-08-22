"""The index has to know which corpus it was built from.

Everything downstream of the index agrees with the index. The quoted text
comes from it, the inline marker comes from it, the sources list comes from
it, and `cairn record` writes an evidence bundle out of it — so a corpus
document edited after the last `cairn index` produces a fluent, confident,
correctly-cited answer quoting a paragraph the cited document no longer
contains, and *nothing anywhere else in this system can tell*. Not the audit:
the bundle is recorded from the same stale index. Not the live check: the
server reads the same file. It is the one failure this repository's own
machinery is structurally blind to.

So the index stores a fingerprint of the corpus files it was built from, and
`read_index` will not hand back an index without being told which corpus it is
supposed to describe.

Three properties, and each one is here because it can be broken silently:

1. **The fingerprint moves when the corpus does** — for every kind of change,
   not just an edit to a body paragraph.
2. **It is a fingerprint of what the loader reads.** A hash over a different
   set of files than `load_corpus` opens would report "unchanged" across the
   edit it exists to catch.
3. **Every subcommand that can answer refuses a stale index.** Enumerated from
   the parser's own subcommand registry rather than from a list written here,
   because a list written here is a list a new subcommand is missing from.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cairn.cli import build_parser
from cairn.corpus import CorpusError, corpus_paths, fingerprint, load_corpus
from cairn.index import (
    INDEX_FORMAT_VERSION,
    IndexError_,
    StaleIndexError,
    build_and_write,
    build_index,
    read_index,
    write_index,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"

# Appended to a corpus document to move it. Deliberately not a word the demo
# questions use, so the change is to the corpus and not to any measured score.
EDIT = "\n\nAn appended paragraph, present only to move the fingerprint.\n"


class CorpusCopy(unittest.TestCase):
    """A writable copy of the demo corpus, so edits are real edits."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.corpus = self.workspace / "corpus"
        shutil.copytree(DEMO, self.corpus)
        self.index_path = self.workspace / "index.json"
        self.addCleanup(self._tmp.cleanup)

    def a_document(self, name: str = "grocery-allowance.en.md") -> Path:
        path = self.corpus / name
        self.assertTrue(path.is_file(), f"the demo corpus no longer has {name}")
        return path


class TestTheFingerprintMovesWithTheCorpus(CorpusCopy):
    def mutated(self, mutate) -> str:
        """The fingerprint of a fresh copy of the demo corpus, after `mutate`."""
        with tempfile.TemporaryDirectory() as scratch:
            corpus = Path(scratch) / "corpus"
            shutil.copytree(DEMO, corpus)
            mutate(corpus)
            return fingerprint(corpus)

    def test_editing_any_document_at_all_moves_it(self):
        # Every document, not one of them. A first draft of this test edited
        # the English grocery document only, and a fingerprint hashing just
        # `*.en.md` passed it — the whole Spanish and Arabic corpus could have
        # been rewritten under an index that called itself current.
        original = fingerprint(DEMO)
        self.assertRegex(original, r"^[0-9a-f]{64}$")
        documents = [p.name for p in corpus_paths(DEMO)]
        self.assertGreaterEqual(len(documents), 3, documents)
        for name in documents:
            with self.subTest(document=name):
                def edit(corpus, name=name):
                    path = corpus / name
                    path.write_text(
                        path.read_text(encoding="utf-8") + EDIT, encoding="utf-8"
                    )

                self.assertNotEqual(self.mutated(edit), original, name)

    def test_the_shape_of_the_corpus_moves_it_too(self):
        original = fingerprint(DEMO)

        def rename(corpus):
            # Same length, same position in sort order — so only hashing the
            # *name* catches it. A version of the fingerprint that hashed the
            # concatenated file contents alone passed every other case here
            # and was blind to this one.
            (corpus / "grocery-allowance.en.md").rename(corpus / "grocery-allowance.eo.md")

        def delete(corpus):
            (corpus / "grocery-allowance.en.md").unlink()

        def add(corpus):
            (corpus / "extra.md").write_text(
                "---\nid: extra\ntitle: Extra\nlang: en\n---\n\nBody.\n", encoding="utf-8"
            )

        for description, mutate in (
            ("a document renamed", rename),
            ("a document deleted", delete),
            ("a document added", add),
        ):
            with self.subTest(change=description):
                self.assertNotEqual(
                    self.mutated(mutate),
                    original,
                    f"{description} left the fingerprint where it was",
                )

    def test_rereading_an_untouched_corpus_gives_the_same_answer(self):
        # The other direction. A fingerprint that moved on its own would make
        # every command fail after a while, and the fix for that would be to
        # stop checking.
        self.assertEqual(fingerprint(self.corpus), fingerprint(self.corpus))
        os.utime(self.a_document(), (0, 0))
        self.assertEqual(
            fingerprint(self.corpus),
            fingerprint(DEMO),
            "content, not timestamps: a checkout has whatever mtimes git gave it",
        )

    def test_it_is_a_fingerprint_of_the_files_the_loader_actually_reads(self):
        # The failure this rules out: a fingerprint over a different set of
        # files than `load_corpus` opens. It would report "unchanged" across
        # an edit to an indexed document — the exact case it exists to catch,
        # now with a check standing behind it.
        self.assertEqual(
            sorted(p.name for p in corpus_paths(self.corpus)),
            sorted(Path(d.path).name for d in load_corpus(self.corpus)),
        )
        # A README in the corpus directory is not a corpus document, and the
        # loader skips it. The fingerprint has to skip it too, or every
        # documentation edit would demand a re-index.
        before = fingerprint(self.corpus)
        (self.corpus / "README.md").write_text("not a corpus document\n", encoding="utf-8")
        self.assertEqual(fingerprint(self.corpus), before)
        self.assertNotIn(
            "README.md", [Path(d.path).name for d in load_corpus(self.corpus)]
        )

    def test_moving_the_corpus_directory_does_not_move_the_fingerprint(self):
        # An operator who unpacks the same corpus somewhere else has the same
        # corpus. Hashing the directory path would say otherwise and send them
        # to re-index for nothing.
        self.assertEqual(fingerprint(self.corpus), fingerprint(DEMO))

    def test_a_missing_corpus_is_an_error_and_not_an_empty_hash(self):
        with self.assertRaises(CorpusError):
            fingerprint(self.workspace / "nowhere")


class TestReadingAnIndexRequiresNamingItsCorpus(CorpusCopy):
    def test_a_stale_index_is_refused(self):
        build_and_write(self.corpus, self.index_path)
        read_index(self.index_path, self.corpus)  # current: no complaint

        document = self.a_document()
        document.write_text(document.read_text(encoding="utf-8") + EDIT, encoding="utf-8")
        with self.assertRaises(StaleIndexError) as caught:
            read_index(self.index_path, self.corpus)
        self.assertIn("cairn index", str(caught.exception))

    def test_what_the_refusal_is_instead_of(self):
        # The value of the guard is only visible against what happens without
        # it, so this test does the unsafe thing on purpose: reads the same
        # stale index with the check explicitly opted out of, and shows the
        # engine answering out of it. The quoted text is the text as it *was*;
        # the citation resolves to a document that now says something else.
        from cairn.config import Config
        from cairn.engine import ask

        document = self.a_document()
        before = document.read_text(encoding="utf-8")
        build_and_write(self.corpus, self.index_path)
        document.write_text(before.replace("$212", "$999"), encoding="utf-8")

        unchecked = read_index(self.index_path, None)
        answer = ask(
            "How much is the monthly grocery allowance for one person?",
            unchecked,
            Config(),
            lang="en",
        ).answer
        self.assertEqual(answer.kind, "grounded")
        self.assertIn("$212", answer.text)
        self.assertIn("$999", document.read_text(encoding="utf-8"))
        self.assertNotIn(
            "$212",
            document.read_text(encoding="utf-8"),
            "the corpus no longer says what the answer just quoted, and the "
            "answer cites the corpus",
        )

    def test_the_check_cannot_be_reached_by_forgetting_an_argument(self):
        # `corpus_dir` has no default. An optional check is a check a caller
        # forgets, and in a reference implementation "a caller" is an agency's
        # deployment.
        import inspect

        signature = inspect.signature(read_index)
        parameter = signature.parameters["corpus_dir"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_an_index_whose_corpus_is_gone_is_refused_too(self):
        # Fail-closed: "cannot be shown to be current" is the state that
        # produces a confident wrong quotation, so it is not a state Cairn
        # answers from. The cost — an index shipped without its corpus is not
        # a supported deployment — is stated in the error.
        build_and_write(self.corpus, self.index_path)
        shutil.rmtree(self.corpus)
        with self.assertRaises(IndexError_) as caught:
            read_index(self.index_path, self.corpus)
        self.assertNotIsInstance(caught.exception, StaleIndexError)
        self.assertIn("cannot be checked against its corpus", str(caught.exception))

    def test_an_index_that_cannot_say_what_it_was_built_from_is_refused(self):
        build_and_write(self.corpus, self.index_path)
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        for bad in ("", "not-a-hash", "5BFA70E8" * 8, None, payload["corpus_fingerprint"][:63]):
            with self.subTest(fingerprint=bad):
                self.index_path.write_text(
                    json.dumps(dict(payload, corpus_fingerprint=bad)), encoding="utf-8"
                )
                with self.assertRaises(IndexError_):
                    read_index(self.index_path, self.corpus)
                # And not by way of the corpus comparison: an index with no
                # readable fingerprint is refused before anything is hashed.
                with self.assertRaises(IndexError_):
                    read_index(self.index_path, None)

    def test_an_index_from_before_the_fingerprint_is_refused_by_version(self):
        # A version-2 index cannot prove it is current, because nothing
        # recorded what it was built from. Refusing it is the whole reason the
        # format version moved.
        self.assertEqual(INDEX_FORMAT_VERSION, 3)
        build_and_write(self.corpus, self.index_path)
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        payload.pop("corpus_fingerprint")
        payload["format_version"] = 2
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(IndexError_) as caught:
            read_index(self.index_path, self.corpus)
        self.assertIn("cairn index", str(caught.exception))

    def test_the_fingerprint_survives_the_round_trip(self):
        built = build_index(self.corpus)
        write_index(built, self.index_path)
        self.assertEqual(built.corpus_fingerprint, fingerprint(self.corpus))
        self.assertEqual(
            read_index(self.index_path, self.corpus).corpus_fingerprint,
            built.corpus_fingerprint,
        )

    def test_the_build_reports_it(self):
        report = build_and_write(self.corpus, self.index_path)
        self.assertEqual(report.corpus_fingerprint, fingerprint(self.corpus))


def subcommands() -> dict[str, argparse.ArgumentParser]:
    """Every subcommand the CLI registers, from the parser itself.

    Not a list written in this file. The lesson that produced this function is
    recorded in WORKLOG: the audit's suite universe came from the two files
    the audit configured, so deleting a suite from both deleted it from the
    universe as well and everything stayed green. A hand-written list of
    subcommands to test has the same shape.
    """
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the CLI no longer registers subcommands")


class TestEverySubcommandThatCanAnswerRefusesAStaleIndex(unittest.TestCase):
    """Run in subprocesses, because one of them is `serve`.

    `serve` blocks forever once it binds. Asserting it refuses has to be able
    to *fail* rather than hang, so every subcommand goes through the same
    subprocess-with-a-timeout path and a command that does not exit is a
    failure with a message.
    """

    # The subcommands that do not answer from the index: `index` is the fix,
    # not a reader; `lint` reads the corpus directly and never touches an
    # index; `config` reads only `cairn.toml`; `diff` compares two corpus
    # directories named on the command line, not the configured one. Anything
    # else added to this set is somebody deciding a new command may quote a
    # corpus it has not checked.
    DOES_NOT_ANSWER = {"index", "lint", "config", "diff"}

    # Arguments each subcommand needs to get as far as reading the index.
    # A subcommand with no entry here fails the completeness test below rather
    # than being skipped.
    ARGV = {
        "index": [],
        "lint": [],
        "config": [],
        "diff": [str(DEMO), str(DEMO)],
        "ask": ["a question"],
        "serve": ["--port", "0"],
        "record": [],  # --out is added per-run, into the temp workspace
    }

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._tmp.name)
        cls.corpus = cls.workspace / "corpus"
        shutil.copytree(DEMO, cls.corpus)
        cls.config = cls.workspace / "cairn.toml"
        cls.config.write_text(
            f'[corpus]\npath = "{cls.corpus}"\n'
            f'[index]\npath = "{cls.workspace / "index.json"}"\n',
            encoding="utf-8",
        )
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
        build_and_write(cls.corpus, cls.workspace / "index.json")
        # Now the corpus moves and the index does not.
        document = cls.corpus / "grocery-allowance.en.md"
        document.write_text(document.read_text(encoding="utf-8") + EDIT, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_subcommand(self, name: str, argv: list[str]):
        try:
            return subprocess.run(
                [sys.executable, "-m", "cairn", "--config", str(self.config), name, *argv],
                cwd=self.workspace, env=self.env, capture_output=True, text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.fail(
                f"`cairn {name}` did not exit within 30s against a stale index. "
                f"It is answering, or serving, out of an index whose corpus has "
                f"changed underneath it."
            )

    def test_the_argument_table_covers_every_subcommand(self):
        self.assertEqual(set(self.ARGV), set(subcommands()))
        self.assertTrue(self.DOES_NOT_ANSWER <= set(subcommands()))

    def test_each_one_refuses(self):
        checked = 0
        for name in sorted(subcommands()):
            if name in self.DOES_NOT_ANSWER:
                continue
            argv = list(self.ARGV[name])
            if name == "record":
                argv += ["--out", str(self.workspace / f"bundle-{name}")]
            with self.subTest(subcommand=name):
                completed = self.run_subcommand(name, argv)
                self.assertEqual(
                    completed.returncode, 1,
                    f"`cairn {name}` exited {completed.returncode}\n"
                    f"stdout: {completed.stdout[:400]}",
                )
                self.assertIn("has changed since the index was built", completed.stderr)
                self.assertIn("Re-run `cairn index`", completed.stderr)
                self.assertEqual(completed.stdout, "", "nothing was answered")
                checked += 1
        self.assertGreaterEqual(checked, 3, "the subcommand registry came back empty")

    def test_indexing_again_is_the_documented_fix(self):
        # The error tells the operator to run `cairn index`. If that did not
        # actually clear it, the message would be sending them in a circle.
        rebuilt = self.run_subcommand("index", [])
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
        self.assertIn("Corpus fingerprint:", rebuilt.stdout)
        answered = self.run_subcommand("ask", ["a question"])
        self.assertEqual(answered.returncode, 0, answered.stderr)
        # Put the stale index back for any test that runs after this one.
        document = self.corpus / "grocery-allowance.en.md"
        document.write_text(document.read_text(encoding="utf-8") + EDIT, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
