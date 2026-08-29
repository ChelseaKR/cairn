"""CLI behavior: exit codes, reporting, JSON output, milestone stubs."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from cairn import __version__
from cairn.cli import build_parser, main
from cairn.language import POP_DIRECTIONAL_ISOLATE

ROOT = Path(__file__).resolve().parent.parent


class CliHarness(unittest.TestCase):
    """Runs the CLI in-process against a temp config + index."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.index_path = Path(cls._tmp.name) / "index.json"
        cls.config_path = Path(cls._tmp.name) / "cairn.toml"
        cls.config_path.write_text(
            "[corpus]\n"
            f'path = "{(ROOT / "corpus" / "demo").as_posix()}"\n'
            "[index]\n"
            f'path = "{cls.index_path.as_posix()}"\n',
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(self.config_path), *argv])
        return code, out.getvalue(), err.getvalue()


class TestCli(CliHarness):
    def test_01_index_reports_counts_and_path(self):
        code, out, _ = self.run_cli("index")
        self.assertEqual(code, 0)
        self.assertIn("Indexed 44 passages from 11 documents", out)
        self.assertIn("(11 marked synthetic)", out)
        # The path in `out` is what `cairn.toml` says, byte for byte — the
        # CLI never re-normalizes it through Path — and this harness's own
        # config writes it out with as_posix() (see setUpClass) so the value
        # is valid TOML on every platform. Compare against that same form.
        self.assertIn(self.index_path.as_posix(), out)

    def test_02_ask_grounded_json(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "How much is the monthly grocery allowance for one person?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "grounded")
        self.assertIn("$212", payload["text"])
        self.assertTrue(payload["sources"])

    def test_03_ask_refusal_exits_zero_no_sources_section(self):
        self.run_cli("index")
        code, out, _ = self.run_cli("ask", "Can you help me renew my drivers license?")
        self.assertEqual(code, 0, "refusal is a first-class outcome, not an error")
        self.assertNotIn("Sources:", out)

    def test_ask_without_index_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.toml"
            cfg.write_text(
                f'[corpus]\npath = "{(ROOT / "corpus" / "demo").as_posix()}"\n'
                f'[index]\npath = "{(Path(tmp) / "missing.json").as_posix()}"\n',
                encoding="utf-8",
            )
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--config", str(cfg), "ask", "anything"])
            self.assertEqual(code, 1)
            self.assertIn("cairn index", err.getvalue())

    def test_04_ask_explain_reports_the_trace_alongside_the_answer(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--explain", "How much is the monthly grocery allowance for one person?"
        )
        self.assertEqual(code, 0)
        self.assertIn("Attempt 1 (restricted to 'en')", out)
        self.assertIn("Stage 1 - retrieval:", out)
        self.assertIn("Stage 2 - answer:", out)
        self.assertIn("Verdict: GROUNDED", out)
        self.assertIn("Sources:", out, "the answer itself is still printed")
        # Same reasoning as test_01 above: compare against the form written
        # into cairn.toml, since that is the form the CLI echoes back.
        self.assertIn(
            self.index_path.as_posix(), out, "the trace names the index it read"
        )

    def test_05_ask_explain_json_carries_candidates_and_diagnosis(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "--explain", "Can you help me renew my drivers license?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "refusal")
        explain = payload["explain"]
        self.assertEqual(explain["threshold"], 0.165)
        self.assertTrue(
            explain["candidates"],
            "a refusal still shows what was considered and rejected; all([]) is True",
        )
        self.assertTrue(all(not c["accepted"] for c in explain["candidates"]))
        self.assertEqual(explain["diagnosis"]["blame"], "retrieval")
        self.assertFalse(explain["diagnosis"]["grounded"])
        self.assertEqual(
            [s["stage"] for s in explain["diagnosis"]["stages"]], ["retrieval", "answer"]
        )
        self.assertEqual(explain["language"]["lang"], "en")
        self.assertEqual([a["scope"] for a in explain["attempts"]], ["language", "corpus"])
        self.assertFalse(explain["cross_language"])

    def test_06_explain_is_opt_in(self):
        self.run_cli("index")
        _, plain, _ = self.run_cli("ask", "--json", "How much does the GoPass cost per year?")
        self.assertNotIn("explain", json.loads(plain))

    def test_07_index_reports_the_languages_it_indexed(self):
        _, out, _ = self.run_cli("index")
        self.assertIn("4 languages [ar, en, es, fr]", out)

    def test_08_lang_selects_the_answer_language(self):
        self.run_cli("index")
        code, out, _ = self.run_cli(
            "ask", "--json", "--lang", "ar", "How much is the grocery allowance?"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["lang"], "ar")
        self.assertEqual(payload["dir"], "rtl")

    def test_09_rtl_output_isolates_latin_source_ids(self):
        self.run_cli("index")
        _, out, _ = self.run_cli("ask", "كم تحصل الأسرة المكونة من شخص واحد شهريًا؟")
        self.assertIn("المصادر:", out, "the sources heading speaks the answer language")
        self.assertIn(POP_DIRECTIONAL_ISOLATE, out, "Latin ids are bidi-isolated")

    def test_10_an_unsupported_language_is_an_error_not_a_bad_answer(self):
        self.run_cli("index")
        code, out, err = self.run_cli("ask", "--lang", "tlh", "anything")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("unsupported language", err)

    def test_11_serve_binds_to_this_machine_only_by_default(self):
        # A demo server that listens on every interface by default is a demo
        # server someone accidentally exposes. The behaviour of the server
        # itself is covered in tests/test_ui.py.
        args = build_parser().parse_args(["serve"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        # The default is loopback, and it is loopback because the parser says
        # so and not because something downstream rewrites it. What stood here
        # was `assertIs(x if not hasattr(x, "__wrapped__") else x.__wrapped__, x)`,
        # which is `assertIs(f, f)` for any unwrapped function and false for
        # any wrapped one: there is no input under which it carries
        # information. Explicit host still wins, which is the behaviour a
        # default is only meaningful against.
        self.assertEqual(build_parser().parse_args(["serve", "--host", "0.0.0.0"]).host,
                         "0.0.0.0")
        self.assertNotIn("0.0.0.0", (args.host, ""))


class TestTheVersionIsRecordedOnce(unittest.TestCase):
    """The argument this repository makes about `plumbline.pin`, turned around.

    `tests/test_interlock.py` greps the tree to prove the pinned harness
    commit appears in exactly one file, because "a version recorded in two
    places is a version that will disagree with itself". Cairn's own version
    is recorded in two places — `cairn/__init__.py` and `pyproject.toml` —
    and nothing was holding them together, or checking that `--version`
    reports either of them.

    Four places now. `CITATION.cff` names a version, and it is the one a
    stranger reads: the panel GitHub renders from it is how a reference
    implementation gets referred to at all, so a version that drifted there
    would be a wrong number in somebody else's bibliography. `CHANGELOG.md`
    names one too, and a changelog whose newest section is not the current
    version is a changelog describing a release that does not exist.

    Five places, since the fifth one drifted. The README's status paragraph
    and its Release & Versioning row both say which version is current, and
    both sat at `v0.2.0` for six days after 0.3.0 shipped — through a tag, a
    GitHub Release, a successful `release.yml` run, and a PyPI upload. The
    four checks above were all green the whole time, because none of them
    reads the README. Underclaiming is the same defect as overclaiming: the
    sentence was a statement about the artifact and it was false.

    Correcting the sentence was the first half. This is the second: the
    README's version prose is now derived from `__version__` and from the
    changelog rather than typed beside them.
    """

    def test_the_package_and_the_packaging_agree(self):
        declared = re.search(
            r'(?m)^version = "([^"]+)"',
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(declared, "pyproject.toml declares no version")
        self.assertEqual(declared.group(1), __version__)

    def test_the_citation_metadata_agrees(self):
        # A one-line parse rather than a YAML dependency, for the same reason
        # tests/test_rulesets.py parses the workflow itself: the core path of
        # this repository is standard library only.
        cited = re.search(
            r"(?m)^version:\s*(\S+)\s*$",
            (ROOT / "CITATION.cff").read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(cited, "CITATION.cff declares no version")
        self.assertEqual(cited.group(1).strip("\"'"), __version__)

    def test_the_changelog_describes_this_version(self):
        headings = re.findall(
            r"(?m)^## (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        )
        self.assertTrue(headings, "the changelog has no version sections")
        self.assertEqual(headings[0], __version__, "the newest section is not this version")

    def readme(self):
        return (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_readme_status_line_names_this_version(self):
        # The first thing a reader sees. It named v0.2.0 while 0.3.0 was on
        # PyPI, which is the drift this test exists for.
        named = re.search(r"\*\*Status: released\.\*\* `v(\d+\.\d+\.\d+)` is the current version", self.readme())
        self.assertIsNotNone(named, "the README status line no longer names a current version")
        self.assertEqual(named.group(1), __version__)

    def test_the_conformance_row_names_this_version(self):
        stated = re.search(r"is held together by a test, currently (\d+\.\d+\.\d+)\.", self.readme())
        self.assertIsNotNone(stated, "the Release & Versioning row no longer names a version")
        self.assertEqual(stated.group(1), __version__)

    def test_the_readme_names_the_current_version_on_pypi(self):
        stated = re.search(r"`cairn-assistant` (\d+\.\d+\.\d+) is the current PyPI version", self.readme())
        self.assertIsNotNone(stated, "the README no longer names a current PyPI version")
        self.assertEqual(stated.group(1), __version__)

    COUNT_WORDS = {
        1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
        6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
    }

    def released_versions(self):
        """Every version the changelog has a section for, newest first.

        The changelog is the offline record of what was released. `git tag` is
        the other one and is not used here: CI clones shallow and without
        tags, so a check that read them would pass locally and be vacuous
        where it matters.
        """
        return re.findall(r"(?m)^## (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_the_readme_lists_every_released_version(self):
        released = self.released_versions()
        sentence = re.search(r"(\w+) tagged releases exist: ([^\u2014]+)", self.readme())
        self.assertIsNotNone(sentence, "the README no longer lists the tagged releases")
        listed = re.findall(r"`v(\S+?)`", sentence.group(2))
        self.assertEqual(
            sorted(listed), sorted(released),
            "the README's release list and the changelog's sections disagree",
        )

    def test_the_readme_counts_the_releases_it_lists(self):
        released = self.released_versions()
        sentence = re.search(r"(\w+) tagged releases exist:", self.readme())
        self.assertIsNotNone(sentence, "the README no longer counts the tagged releases")
        self.assertEqual(
            sentence.group(1), self.COUNT_WORDS.get(len(released)),
            f"the README says {sentence.group(1)!r} where the changelog has {len(released)}",
        )

    def test_the_readme_claims_no_release_the_changelog_does_not_have(self):
        # A version anywhere in the README that the changelog has no section
        # for is a release being described before it exists. The reverse --
        # a released version the README never mentions -- is fine: not every
        # release needs a sentence.
        released = set(self.released_versions())
        for shown in set(re.findall(r"`v(\d+\.\d+\.\d+)`", self.readme())):
            with self.subTest(version=shown):
                self.assertIn(
                    shown, released,
                    f"the README names v{shown}, which the changelog has no section for",
                )

    def test_the_cli_reports_it(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"cairn {__version__}")


if __name__ == "__main__":
    unittest.main()
