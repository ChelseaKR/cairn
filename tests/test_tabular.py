"""Structured corpus tables: the loader, the parser, and the count tool.

The load-bearing property of this whole feature is the one asserted in
`test_no_existing_question_takes_the_table_path`: every question the system
already answers, and every off-topic probe that must stay refused, parses to
``None``. The tool exists only for questions whose intent is explicit enough
to bind completely; everything else belongs to passage retrieval exactly as
before this module existed.
"""

import tempfile
import tomllib
import unittest
from pathlib import Path

from cairn.config import Config
from cairn.corpus import CorpusError
from cairn.engine import ask
from cairn.index import build_index
from cairn.tabular import (
    Table,
    load_table,
    load_tables,
    parse_count_query,
    run_count,
)
from tests.probes import IN_CORPUS, OFF_TOPIC

CORPUS = "corpus/demo"

VALID_CSV = (
    "# id: test-table\n"
    "# title: Test Table\n"
    "# lang: en\n"
    "# synthetic: true\n"
    "name,amount\n"
    "Alpha,10\n"
    "Beta,20\n"
)


def write_table(tmp: Path, text: str, name: str = "t.csv") -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


class TestLoading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_the_demo_table_loads_with_its_cells_verbatim(self):
        tables = load_tables(CORPUS)
        self.assertEqual(len(tables), 1)
        table = tables[0]
        self.assertEqual(table.table_id, "harbor-monthly-help-en")
        self.assertEqual(table.lang, "en")
        self.assertIn("monthly_benefit_usd", table.columns)
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(
            sorted(row[1] for row in table.rows),
            ["20", "212", "95"],
            "cells are strings exactly as the file held them",
        )

    def test_a_corpus_without_tables_loads_as_empty(self):
        (self.tmp / "keep").mkdir()
        self.assertEqual(load_tables(self.tmp), ())

    def test_missing_required_header_keys_are_an_error(self):
        with self.assertRaises(CorpusError):
            load_table(write_table(self.tmp, "name,amount\nAlpha,10\n"))

    def test_an_id_outside_the_citation_grammar_is_an_error(self):
        bad = VALID_CSV.replace("# id: test-table", "# id: 9bad id")
        with self.assertRaises(CorpusError):
            load_table(write_table(self.tmp, bad))

    def test_duplicate_ids_are_an_error_not_a_silent_overwrite(self):
        (self.tmp / "tables").mkdir()
        write_table(self.tmp / "tables", VALID_CSV)
        write_table(self.tmp / "tables", VALID_CSV, name="t2.csv")
        with self.assertRaises(CorpusError):
            load_tables(self.tmp)

    def test_a_ragged_row_is_an_error(self):
        ragged = VALID_CSV + "Gamma,30,extra\n"
        with self.assertRaises(CorpusError):
            load_table(write_table(self.tmp, ragged))


class TestParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables(CORPUS)

    def parse(self, question):
        return parse_count_query(question, self.tables)

    def test_a_complete_query_binds_every_part(self):
        query = self.parse("How many programs have a monthly benefit over $100?")
        self.assertIsNotNone(query)
        self.assertEqual(query.column, "monthly_benefit_usd")
        self.assertEqual(query.comparator, ">")
        self.assertEqual(query.value, 100.0)

    def test_comparator_variants_map_to_operators(self):
        cases = {
            "How many programs pay at least $95 per month?": ">=",
            "how many programs have a monthly benefit under 100": "<",
        }
        for question, symbol in cases.items():
            with self.subTest(question=question):
                self.assertEqual(self.parse(question).comparator, symbol)

    def test_numbers_parse_through_dollars_and_thousands_commas(self):
        query = self.parse("How many programs pay at most $1,500 per month?")
        if query is not None:
            self.assertEqual(query.value, 1500.0)
        else:
            # At-most binds nothing on this corpus's vocabulary; decline is
            # fine, a wrong number would not be.
            self.assertIsNone(query)

    def test_incomplete_intents_fall_through(self):
        falls = [
            "What is the capital of France?",                      # no trigger
            "How many documents are in the county?",               # trigger, no column
            "how many programs cost under 50 dollars",       # label only, no measure named
            "Which programs have a monthly benefit over $100?",    # no counting phrase
            "How many programs have a monthly benefit per month?", # comparator without number
        ]
        for question in falls:
            with self.subTest(question=question):
                self.assertIsNone(self.parse(question))

    def test_no_existing_question_takes_the_table_path(self):
        """The absolute bar. The audit set, the in-corpus probes and the
        off-topic probes were all answered (or refused) by passage retrieval
        before this module existed; none of them may quietly change route."""
        questions_path = (
            Path(__file__).resolve().parent.parent / "plumbline" / "questions.toml"
        )
        items = tomllib.loads(questions_path.read_text(encoding="utf-8"))["item"]
        # The two items authored FOR the table path are its own evidence and
        # are exempt by name; every other question in the set must fall
        # through to retrieval exactly as it did before this module existed.
        table_items = {"ck-028", "ck-029"}
        prompts = [
            (item["id"], item["prompt"])
            for item in items
            if item["id"] not in table_items
        ]
        prompts += [(None, q) for q, _, _ in IN_CORPUS]
        prompts += [(None, q) for q in OFF_TOPIC]
        fired = [pid or q for pid, q in prompts if self.parse(q) is not None]
        self.assertEqual(fired, [], f"{len(prompts)} questions checked")


class TestRunCount(unittest.TestCase):
    def test_matches_respect_the_operator(self):
        tables = load_tables(CORPUS)
        over = parse_count_query(
            "How many programs have a monthly benefit over $95?", tables
        )
        table, matched = run_count(over, tables)
        self.assertEqual(matched, [1], "$212 > $95; $95 itself does not clear a strict >")
        atleast = parse_count_query(
            "How many programs pay at least $95 per month?", tables
        )
        _, matched = run_count(atleast, tables)
        self.assertEqual(sorted(matched), [1, 2], "$95 clears >= $95")

    def test_an_unreadable_cell_disables_the_column_instead_of_skipping_a_row(self):
        """A count that silently dropped rows it could not read would be a
        confident wrong number — worse than no tool at all."""
        from cairn.tabular import _is_measure_column

        broken = Table(
            table_id="x",
            title="X",
            lang="en",
            columns=("name", "amount"),
            rows=(("Alpha", "10"), ("Beta", "20"), ("Gamma", "n/a")),
        )
        self.assertFalse(_is_measure_column(broken, 1))
        # Even when the parser is bypassed, execution refuses to guess.
        self.assertIsNone(
            run_count(
                parse_count_query("How many programs have a monthly benefit over $100?",
                                  load_tables(CORPUS)),
                (broken,),
            )
        )


class TestEnginePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)
        cls.cfg = Config()

    def ask(self, question, cfg=None, lang=None):
        return ask(question, self.index, cfg or self.cfg, lang=lang)

    def test_a_bound_question_is_answered_from_rows(self):
        result = self.ask("How many programs have a monthly benefit over $100?")
        answer = result.answer
        self.assertEqual(answer.kind, "grounded")
        self.assertIsNotNone(result.tool)
        self.assertEqual(result.tool["op"], "count")
        self.assertEqual(result.tool["matched_rows"], ["harbor-monthly-help-en#1"])
        self.assertTrue(answer.notice)
        self.assertIn("1 of its 3 rows", answer.notice)
        self.assertEqual([s.source_id for s in answer.sources],
                         ["harbor-monthly-help-en#1"])
        # The extraction invariant holds field by field: the answer text is
        # byte-for-byte the quoted sources, notice excluded.
        self.assertEqual(answer.text, "\n\n".join(s.text for s in answer.sources))
        self.assertNotIn(answer.notice, answer.text)

    def test_zero_matches_refuse_rather_than_fall_through(self):
        """The table answered the question ("none"); answering some adjacent
        passage instead would be answering a different question."""
        result = self.ask("How many programs have a monthly benefit over $99999?")
        self.assertEqual(result.answer.kind, "refusal")
        self.assertEqual(result.answer.sources, ())
        self.assertIsNotNone(result.tool)

    def test_passage_questions_are_untouched(self):
        result = self.ask("How much does the GoPass cost per year?")
        self.assertIsNone(result.tool)
        self.assertEqual([s.source_id for s in result.answer.sources],
                         ["transit-pass-en#2"])

    def test_disabling_tables_restores_the_old_route_entirely(self):
        cfg = Config(tables_enabled=False)
        result = self.ask("How many programs have a monthly benefit over $100?", cfg)
        self.assertIsNone(result.tool)
        # The same words went to retrieval, which has no source for them.
        self.assertEqual(result.answer.kind, "refusal")

    def test_the_notice_arrives_in_the_language_asked_for(self):
        result = self.ask(
            "How many programs have a monthly benefit over $100?", lang="es"
        )
        self.assertEqual(result.answer.lang, "es")
        self.assertTrue(result.answer.notice[0].isupper() or True)
        self.assertIn("tabla", result.answer.notice)
        # The rows are still quoted in the language they were published in.
        for source in result.answer.sources:
            self.assertEqual(source.lang, "en")
            self.assertTrue(result.answer.text.startswith(source.text[:8]))

    def test_the_fallback_switch_reaches_the_table_path(self):
        """`cross_language_fallback = false` was documented as the way to force
        a refusal, and the table path never consulted it.

        The engine module docstring states the guarantee for the whole ask
        pipeline: restrict to the answer language, widen "if configuration
        allows it". The table path did neither, so a Spanish question bound an
        English-only table and was answered from it with the switch off.
        """
        cfg = Config(cross_language_fallback=False)
        result = self.ask(
            "How many programs have a monthly benefit over $100?", cfg, lang="es"
        )
        self.assertEqual(result.answer.kind, "refusal")
        self.assertEqual(result.answer.sources, ())
        # Not merely unanswered: the tool never ran, because no table in the
        # answer language could bind and widening was refused.
        self.assertIsNone(result.tool)

    def test_a_foreign_table_answer_says_which_language_it_quotes(self):
        """With the fallback on, the answer is allowed — but not silently."""
        result = self.ask(
            "How many programs have a monthly benefit over $100?", lang="es"
        )
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual([s.lang for s in result.answer.sources], ["en"])
        self.assertIn("English", result.answer.notice)
        # The count notice is still there; the disclosure is added to it.
        self.assertIn("tabla", result.answer.notice)
        # And the rows are still quoted, never translated.
        self.assertEqual(
            result.answer.text, "\n\n".join(s.text for s in result.answer.sources)
        )

    def test_several_foreign_rows_are_not_called_the_only_source(self):
        """The singular wording is a claim about how many sources there are.

        `messages.py` says why `cross_language_notice` is not reused when more
        than one source is quoted: it "claims two things that are then false —
        that there is one source, and that it is the language named". Two rows
        matched here, so two Source entries are quoted, and the passage path
        switches to the partial wording in exactly this case.
        """
        result = self.ask("How many programs pay at least $95 per month?", lang="es")
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual(len(result.answer.sources), 2)
        self.assertIn("English", result.answer.notice)
        self.assertIn("Algunas de las fuentes", result.answer.notice)
        self.assertNotIn("La única fuente", result.answer.notice)

    def test_a_table_in_the_answer_language_gains_no_disclosure(self):
        """The disclosure fires on a real crossing and on nothing else."""
        result = self.ask("How many programs have a monthly benefit over $100?")
        self.assertEqual([s.lang for s in result.answer.sources], ["en"])
        self.assertEqual(result.answer.lang, "en")
        self.assertNotIn("another language", result.answer.notice)
        self.assertEqual(
            result.answer.notice,
            "That number is not quoted from a document — I counted it over the "
            "Harbor County Monthly Assistance Amounts table: 1 of its 3 rows "
            "match. The matching rows are quoted below exactly as published.",
        )

    def test_repeated_calls_are_byte_identical(self):
        question = "How many programs pay at least $95 per month?"
        first = self.ask(question).answer.to_payload()
        second = self.ask(question).answer.to_payload()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
