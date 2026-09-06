"""Plain-language readability: the grades, and the languages that get none.

The property this file is really about is the second one. A readability
number is easy to produce for any text at all — the arithmetic does not
know what language it was fitted on — and producing one for Arabic or French
here would be the portfolio's most common defect wearing a new hat: an
absence rendered as a value. Several tests below check not that the right
number appears but that no number appears.
"""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from cairn import stream, text
from cairn.cli import main
from cairn.config import Config, ConfigError, load_config
from cairn.lint import lint_corpus, render
from cairn.readability import (
    BUILTIN_FORMULAS,
    CRAWFORD_GRADE,
    FLESCH_KINCAID_GRADE,
    FORMULA_SOURCES,
    ReadabilityError,
    formula_for,
    measure,
    sentences,
    summarize,
    syllables_en,
    syllables_es,
    validate_formulas,
    words,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"

# Any decimal number at all. Used to prove that an unsupported language's
# rendered line carries no measurement, rather than checking for one wrong
# number and missing every other wrong number.
ANY_NUMBER = re.compile(r"\d")


def write_doc(directory: Path, name: str, *, front_matter: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return path


class TestOneIdeaOfASentence(unittest.TestCase):
    def test_the_sentence_rule_is_the_one_the_streamer_uses(self):
        """Not an equal regex. The same object, so they cannot drift."""
        self.assertIs(text.SENTENCE_END, stream.SENTENCE_END)

    def test_text_with_no_terminator_is_one_sentence(self):
        self.assertEqual(sentences("a clause with no full stop"), 1)

    def test_empty_text_is_no_sentences(self):
        self.assertEqual(sentences("   \n  "), 0)

    def test_an_arabic_question_mark_ends_a_sentence(self):
        self.assertEqual(sentences("ما هذا؟ نعم."), 2)

    def test_a_decimal_point_does_not_end_a_sentence(self):
        self.assertEqual(sentences("The limit is 20.50 dollars a month."), 1)


class TestCounting(unittest.TestCase):
    def test_words_are_the_words_the_author_wrote(self):
        """Not `cairn.text.tokenize`, which stems and drops short tokens."""
        self.assertEqual(words("The cat is on a mat"), ["The", "cat", "is", "on", "a", "mat"])

    def test_a_hyphenated_word_is_one_word(self):
        self.assertEqual(words("plain-language guidance"), ["plain-language", "guidance"])

    def test_bare_digits_are_not_words(self):
        self.assertEqual(words("555 0142"), [])

    def test_english_syllables(self):
        self.assertEqual(syllables_en("cat"), 1)
        self.assertEqual(syllables_en("water"), 2)
        self.assertEqual(syllables_en("assistance"), 3)
        self.assertEqual(syllables_en("make"), 1)  # silent final e
        self.assertEqual(syllables_en("little"), 2)  # -le keeps its vowel
        self.assertEqual(syllables_en("rhythm"), 1)  # no vowel group, floored at 1

    def test_spanish_syllables(self):
        self.assertEqual(syllables_es("casa"), 2)
        self.assertEqual(syllables_es("ayuda"), 3)
        self.assertEqual(syllables_es("solicitud"), 4)
        self.assertEqual(syllables_es("menús"), 2)


class TestAGradeIsComputed(unittest.TestCase):
    def test_english_uses_flesch_kincaid_and_the_arithmetic_checks_out(self):
        result = measure("The cat sat on the mat.", "en")
        self.assertEqual(result.formula, FLESCH_KINCAID_GRADE)
        self.assertEqual(result.words, 6)
        self.assertEqual(result.sentences, 1)
        self.assertEqual(result.syllables, 6)
        # 0.39 * (6/1) + 11.8 * (6/6) - 15.59
        self.assertAlmostEqual(result.grade, 0.39 * 6 + 11.8 - 15.59, places=9)

    def test_spanish_uses_crawford_and_the_arithmetic_checks_out(self):
        result = measure("El gato come pan.", "es")
        self.assertEqual(result.formula, CRAWFORD_GRADE)
        self.assertEqual(result.words, 4)
        self.assertEqual(result.sentences, 1)
        words_per_sentence = 4 / 1
        expected = (
            -0.205 * (100 / words_per_sentence) + 0.049 * (100 * result.syllables / 4) - 3.407
        )
        self.assertAlmostEqual(result.grade, expected, places=9)

    def test_a_longer_sentence_reads_at_a_higher_grade(self):
        short = measure("Bring the form. We will help.", "en").grade
        long = measure(
            "Applicants must subsequently substantiate their continued "
            "eligibility by furnishing documentation demonstrating "
            "uninterrupted residency throughout the determination period.",
            "en",
        ).grade
        assert short is not None and long is not None
        self.assertGreater(long, short)

    def test_mean_sentence_length_is_words_over_sentences(self):
        result = measure("One two three. Four five six.", "en")
        self.assertEqual(result.mean_sentence_length, 3.0)

    def test_mean_sentence_length_over_no_sentences_is_absent_not_zero(self):
        result = measure("   ", "en")
        self.assertEqual(result.sentences, 0)
        self.assertIsNone(result.mean_sentence_length)

    def test_every_named_formula_has_a_published_source(self):
        for name in BUILTIN_FORMULAS.values():
            self.assertIn(name, FORMULA_SOURCES)
            self.assertRegex(FORMULA_SOURCES[name], r"\(\d{4}\)")


class TestAnAbsentFormulaIsAnAbsence(unittest.TestCase):
    def test_arabic_gets_no_grade_and_no_number_at_all(self):
        result = measure("مرحبا بالعالم. هذا نص.", "ar")
        self.assertIsNone(result.grade)
        self.assertEqual(result.formula, "")
        self.assertEqual(result.reason, "no formula in force for ar")
        line = result.describe()
        self.assertIn("n/a", line)
        self.assertIsNone(ANY_NUMBER.search(line))

    def test_french_gets_no_grade_even_though_the_words_are_latin(self):
        """The characters would not stop the English formula. The rule does."""
        result = measure("Le programme aide les familles. Il est gratuit.", "fr")
        self.assertIsNone(result.grade)
        self.assertIsNone(ANY_NUMBER.search(result.describe()))

    def test_an_empty_passage_is_unmeasured_not_grade_zero(self):
        result = measure("   \n  ", "en")
        self.assertIsNone(result.grade)
        self.assertEqual(result.reason, "no words to measure")
        self.assertIn("n/a", result.describe())

    def test_a_passage_of_only_digits_is_unmeasured_not_grade_zero(self):
        result = measure("555 0142 20.50", "en")
        self.assertIsNone(result.grade)
        self.assertEqual(result.words, 0)

    def test_a_summary_over_no_graded_passages_carries_no_mean(self):
        rows = summarize([("p1", measure("مرحبا.", "ar"))])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].mean_grade)
        self.assertIsNone(rows[0].max_grade)
        self.assertIsNone(ANY_NUMBER.search(rows[0].describe().split("passage(s)")[1]))


class TestAnOperatorMayDeclareAFormula(unittest.TestCase):
    def test_the_builtin_table_is_english_and_spanish_only(self):
        self.assertEqual(formula_for("en"), FLESCH_KINCAID_GRADE)
        self.assertEqual(formula_for("es"), CRAWFORD_GRADE)
        self.assertEqual(formula_for("ar"), "")
        self.assertEqual(formula_for("fr"), "")

    def test_a_declared_formula_puts_a_language_in_force(self):
        result = measure("Le programme aide les familles.", "fr", {"fr": FLESCH_KINCAID_GRADE})
        self.assertIsNotNone(result.grade)
        self.assertEqual(result.formula, FLESCH_KINCAID_GRADE)
        self.assertIn(FLESCH_KINCAID_GRADE, result.describe())

    def test_an_override_wins_for_a_builtin_language_too(self):
        self.assertEqual(formula_for("en", {"en": CRAWFORD_GRADE}), CRAWFORD_GRADE)

    def test_a_formula_this_build_cannot_compute_is_refused(self):
        with self.assertRaises(ReadabilityError) as caught:
            validate_formulas({"fr": "dale_chall"})
        self.assertIn("lint.readability.fr", str(caught.exception))

    def test_the_builtin_names_pass_validation(self):
        validate_formulas(dict(BUILTIN_FORMULAS))


class TestConfig(unittest.TestCase):
    def test_no_ceiling_by_default_and_absence_is_not_zero(self):
        self.assertIsNone(Config().lint_max_grade)
        self.assertEqual(Config().readability_by_language, {})

    def test_a_negative_ceiling_is_refused_at_construction(self):
        with self.assertRaises(ConfigError):
            Config(lint_max_grade=-0.1)

    def test_a_ceiling_of_zero_is_allowed(self):
        self.assertEqual(Config(lint_max_grade=0.0).lint_max_grade, 0.0)

    def test_an_unknown_formula_is_refused_at_construction_not_at_measure_time(self):
        with self.assertRaises(ConfigError) as caught:
            Config(readability_by_language={"fr": "smog"})
        self.assertIn("not a formula this build implements", str(caught.exception))

    def test_the_toml_keys_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text(
                f'[lint]\nmax_grade = 8\n\n[lint.readability]\nfr = "{FLESCH_KINCAID_GRADE}"\n',
                encoding="utf-8",
            )
            cfg = load_config(path)
        self.assertEqual(cfg.lint_max_grade, 8.0)
        self.assertEqual(cfg.readability_by_language, {"fr": FLESCH_KINCAID_GRADE})

    def test_an_omitted_ceiling_stays_absent_rather_than_becoming_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text("[lint]\n", encoding="utf-8")
            self.assertIsNone(load_config(path).lint_max_grade)

    def test_a_non_numeric_ceiling_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text('[lint]\nmax_grade = "eight"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_a_readability_table_that_is_not_a_table_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text('[lint]\nreadability = "en"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_a_readability_value_that_is_not_a_string_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cairn.toml"
            path.write_text("[lint.readability]\nfr = 3\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


class TestLintIntegration(unittest.TestCase):
    def test_off_by_default_and_the_report_is_what_it_always_was(self):
        without = lint_corpus(DEMO)
        self.assertIsNone(without.readability)
        self.assertNotIn("Readability", render(without))

    def test_asking_for_it_measures_every_passage_including_the_unmeasurable(self):
        report = lint_corpus(DEMO, readability=True)
        self.assertIsNotNone(report.readability)
        assert report.readability is not None
        graded = report.readability.per_passage
        self.assertEqual(len(graded), sum(1 for _ in graded))
        langs = {m.lang for _, m in graded}
        self.assertEqual(langs, {"en", "es", "ar", "fr"})
        ungraded = [m for _, m in graded if m.grade is None]
        self.assertTrue(ungraded)
        self.assertEqual({m.lang for m in ungraded}, {"ar", "fr"})

    def test_the_demo_grades_are_what_the_published_coefficients_give(self):
        """Recomputed here from the passage text, not copied from a run.

        A pinned decimal would pass equally well if the module and this file
        held the same wrong formula. These re-derive both grades from the
        coefficients as the papers print them, using only the word, sentence
        and syllable counts, and then check the rendered line separately so
        the number a reader sees is pinned too.
        """
        report = lint_corpus(DEMO, readability=True)
        assert report.readability is not None
        found = dict(report.readability.per_passage)

        english = found["grocery-allowance-en#1"]
        assert english.grade is not None
        self.assertAlmostEqual(
            english.grade,
            0.39 * (english.words / english.sentences)
            + 11.8 * (english.syllables / english.words)
            - 15.59,
            places=9,
        )

        spanish = found["grocery-allowance-es#1"]
        assert spanish.grade is not None
        self.assertAlmostEqual(
            spanish.grade,
            -0.205 * (100 * spanish.sentences / spanish.words)
            + 0.049 * (100 * spanish.syllables / spanish.words)
            - 3.407,
            places=9,
        )

        self.assertIsNone(found["grocery-allowance-ar#1"].grade)
        self.assertIsNone(found["grocery-allowance-fr#1"].grade)

    def test_the_demo_grades_a_reader_sees_are_pinned(self):
        report = lint_corpus(DEMO, readability=True)
        assert report.readability is not None
        found = dict(report.readability.per_passage)
        self.assertIn("grade 11.0", found["grocery-allowance-en#1"].describe())
        self.assertIn("grade 6.0", found["grocery-allowance-es#1"].describe())

    def test_the_summary_names_the_formula_per_language(self):
        report = lint_corpus(DEMO, readability=True)
        assert report.readability is not None
        rows = {row.lang: row for row in report.readability.by_language}
        self.assertEqual(rows["en"].formula, FLESCH_KINCAID_GRADE)
        self.assertEqual(rows["es"].formula, CRAWFORD_GRADE)
        self.assertEqual(rows["ar"].formula, "")
        self.assertIsNone(rows["ar"].mean_grade)

    def test_a_passage_over_the_ceiling_warns_and_the_lint_still_passes(self):
        report = lint_corpus(DEMO, readability=True, max_grade=1.0)
        self.assertTrue(report.ok)
        self.assertGreater(report.warning_count, 0)
        self.assertIn("over the lint.max_grade", render(report))

    def test_an_unmeasurable_language_never_earns_a_ceiling_warning(self):
        """Not measured is not the same as measured and over.

        A ceiling of 0.0 puts every graded passage in the demo corpus over it,
        so the count of warnings must be exactly the count of graded passages:
        every one of them, and none of the ungraded ones. Counting rather than
        only checking for absence is what makes this fail if the rule flips.
        """
        report = lint_corpus(DEMO, readability=True, max_grade=0.0)
        assert report.readability is not None
        graded = [m for _, m in report.readability.per_passage if m.grade is not None]
        ungraded = [m for _, m in report.readability.per_passage if m.grade is None]
        self.assertTrue(graded and ungraded)
        warnings = [i for i in report.issues if "lint.max_grade" in i.message]
        self.assertEqual(len(warnings), len(graded))
        for issue in warnings:
            self.assertNotIn("-ar#", issue.message)
            self.assertNotIn("-fr#", issue.message)

    def test_no_ceiling_means_no_warnings_however_high_the_grades(self):
        report = lint_corpus(DEMO, readability=True, max_grade=None)
        self.assertEqual(report.warning_count, 0)

    def test_a_declared_formula_reaches_the_lint(self):
        report = lint_corpus(
            DEMO, readability=True, readability_by_language={"fr": FLESCH_KINCAID_GRADE}
        )
        assert report.readability is not None
        french = [m for _, m in report.readability.per_passage if m.lang == "fr"]
        self.assertTrue(french)
        for measurement in french:
            self.assertIsNotNone(measurement.grade)


class TestLintCli(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_the_flag_prints_the_block_and_exits_zero(self):
        code, out = self._run(["lint", "--readability"])
        self.assertEqual(code, 0)
        self.assertIn("Readability:", out)
        self.assertIn(FLESCH_KINCAID_GRADE, out)
        self.assertIn("n/a (no formula in force for ar)", out)

    def test_without_the_flag_nothing_is_printed_about_readability(self):
        code, out = self._run(["lint"])
        self.assertEqual(code, 0)
        self.assertNotIn("Readability", out)
        self.assertNotIn("grade", out)

    def test_index_is_untouched_by_a_corpus_over_the_ceiling(self):
        """`max_grade` warns in lint. It is not a gate on building an index."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "corpus"
            corpus.mkdir()
            write_doc(
                corpus,
                "dense.en.md",
                front_matter="id: dense\ntitle: Dense\nlang: en\nsynthetic: true",
                body=(
                    "## Eligibility determination\n\n"
                    "Applicants must subsequently substantiate their continued "
                    "eligibility by furnishing documentation demonstrating "
                    "uninterrupted residency throughout the determination period "
                    "notwithstanding any intervening administrative "
                    "reconsideration.\n"
                ),
            )
            # `as_posix()`, not `str()`. A Windows path interpolated raw into a
            # TOML basic string is a string full of escape sequences: the CI
            # canary ran this with `path = "D:\\a\\cairn\\...\\corpus"`, where
            # `\\a` is TOML's bell escape, and the config failed to load. The
            # test then reported the wrong thing entirely -- `lint` exiting 1
            # for an unreadable config, read as `lint` failing on readability.
            # Forward slashes are valid paths on Windows and carry no escapes.
            (root / "cairn.toml").write_text(
                f'[corpus]\npath = "{corpus.as_posix()}"\n\n'
                f'[index]\npath = "{(root / "index.json").as_posix()}"\n\n'
                "[lint]\nmax_grade = 6\n",
                encoding="utf-8",
            )
            config = str(root / "cairn.toml")
            lint_code, out = self._run(["--config", config, "lint", "--readability"])
            self.assertEqual(lint_code, 0)
            self.assertIn("over the lint.max_grade", out)
            index_code, _ = self._run(["--config", config, "index"])
            self.assertEqual(index_code, 0)


if __name__ == "__main__":
    unittest.main()
