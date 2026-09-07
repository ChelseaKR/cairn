"""Per-language and per-layer thresholds: resolution, bounds, and reporting.

One threshold for four languages either over-refuses in the narrow band or
over-answers in the wide one. The tables let an operator set each from a
measurement — and the measurement is the other half of this: `calibrate`
reports a band per slice, and `--emit-config` writes what it found without
applying any of it.

The rule every test here is a variation on: **a corpus and a config with no
tables behave exactly as they did before the tables existed.**
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cairn.calibrate import CalibrationReport, ProbeResult, calibrate, emit_config
from cairn.calibrate import render as render_calibration
from cairn.config import Config, ConfigError, load_config
from cairn.engine import ask
from cairn.explain import diagnose, render, trace_payload
from cairn.index import build_index
from cairn.query import split_intents
from cairn.retrieve import retrieve
from tests.layered import layered_index

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
PROBES = Path(__file__).resolve().parent.parent / "docs" / "calibration-probes.example.toml"

ENGLISH = "How much is the monthly grocery allowance for one person?"
ARABIC = "كم تحصل الأسرة المكونة من شخص واحد شهريًا من مخصص البقالة؟"
SPANISH = "Cuanto recibe un hogar de una persona del subsidio de alimentos?"
SONOMA = "us-ca-sonoma"
HOURS = "What are the service counter hours?"


class DemoHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)


# --------------------------------------------------------------------------
# Resolution


class TestResolutionOrder(unittest.TestCase):
    CFG = Config(
        threshold_by_language={"ar": 0.12},
        threshold_by_jurisdiction={"us-ca": 0.31},
    )

    def test_the_default_when_no_table_applies(self):
        self.assertEqual(
            self.CFG.threshold_for(lang="en"), (0.165, "retrieval.threshold")
        )

    def test_a_language_entry_wins_over_the_default(self):
        self.assertEqual(
            self.CFG.threshold_for(lang="ar"),
            (0.12, "retrieval.threshold_by_language.ar"),
        )

    def test_a_jurisdiction_entry_wins_over_a_language_entry(self):
        """Jurisdiction, then language, then the default. A layer is a claim
        about a body of text and a language is a claim about how a question is
        written, so the narrower claim about the corpus wins."""
        self.assertEqual(
            self.CFG.threshold_for(lang="ar", jurisdiction="us-ca"),
            (0.31, "retrieval.threshold_by_jurisdiction.us-ca"),
        )

    def test_a_layer_with_no_entry_falls_to_the_language_not_to_its_parent(self):
        """Inheritance sounds natural and is a trap: an entry for `us` would
        then be a new default for everything under it, which is exactly what
        `retrieval.threshold` already is."""
        self.assertEqual(
            self.CFG.threshold_for(lang="ar", jurisdiction=SONOMA),
            (0.12, "retrieval.threshold_by_language.ar"),
        )

    def test_an_empty_config_resolves_to_the_default_for_everything(self):
        cfg = Config()
        for kwargs in ({}, {"lang": "ar"}, {"lang": "ar", "jurisdiction": SONOMA}):
            with self.subTest(**kwargs):
                self.assertEqual(
                    cfg.threshold_for(**kwargs), (0.165, "retrieval.threshold")
                )

    def test_the_key_names_the_line_an_operator_would_edit(self):
        """The whole point of returning it: a number with no key sends an
        operator to `retrieval.threshold` to watch nothing happen."""
        _, key = self.CFG.threshold_for(lang="ar")
        self.assertEqual(key, "retrieval.threshold_by_language.ar")
        self.assertIn("ar", key)


# --------------------------------------------------------------------------
# Bounds


class TestBoundsAreCheckedWhereTheConfigIsMade(unittest.TestCase):
    """The `max_passages = 0` lesson, applied to the tables: bounds live on
    the object, not only in the loader, because this is a reference
    implementation somebody imports."""

    def test_a_value_outside_the_bound_is_refused(self):
        for value in (0.0, -0.1, 1.5, 2):
            for table in ("threshold_by_language", "threshold_by_jurisdiction"):
                with self.subTest(value=value, table=table):
                    with self.assertRaises(ConfigError):
                        Config(**{table: {"ar": value}})

    def test_zero_is_refused_because_the_base_key_refuses_it(self):
        """An override is held to the bound of the key it overrides, or the
        table becomes a way to write a value `retrieval.threshold` refuses."""
        with self.assertRaises(ConfigError):
            Config(threshold=0.0)
        with self.assertRaises(ConfigError):
            Config(threshold_by_language={"ar": 0.0})

    def test_a_bool_is_not_a_number(self):
        with self.assertRaises(ConfigError):
            Config(threshold_by_language={"ar": True})

    def test_one_is_accepted_at_the_top_of_the_range(self):
        self.assertEqual(
            Config(threshold_by_language={"ar": 1.0}).threshold_for(lang="ar")[0], 1.0
        )

    def test_the_message_names_the_key_and_the_value(self):
        with self.assertRaises(ConfigError) as caught:
            Config(threshold_by_jurisdiction={SONOMA: 3.0})
        message = str(caught.exception)
        self.assertIn(f"retrieval.threshold_by_jurisdiction.{SONOMA}", message)
        self.assertIn("3.0", message)


class TestTheFileAndTheObjectAgree(unittest.TestCase):
    def _config(self, body: str) -> Config:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "cairn.toml"
        path.write_text(body, encoding="utf-8")
        return load_config(path)

    def test_the_tables_are_read(self):
        cfg = self._config(
            "[retrieval.threshold_by_language]\nar = 0.12\n"
            '[retrieval.threshold_by_jurisdiction]\n"us-ca" = 0.31\n'
        )
        self.assertEqual(cfg.threshold_by_language, {"ar": 0.12})
        self.assertEqual(cfg.threshold_by_jurisdiction, {"us-ca": 0.31})

    def test_an_integer_is_read_as_a_number(self):
        """TOML's `1` is a legitimate way to write the top of the range, and
        rejecting it would refuse a file for its spelling."""
        cfg = self._config("[retrieval.threshold_by_language]\nar = 1\n")
        self.assertEqual(cfg.threshold_by_language, {"ar": 1.0})

    def test_an_out_of_range_file_value_is_refused_by_the_loader_too(self):
        with self.assertRaises(ConfigError):
            self._config("[retrieval.threshold_by_language]\nar = 0\n")

    def test_an_absent_section_leaves_the_tables_empty(self):
        cfg = self._config("[corpus]\npath = 'corpus/demo'\n")
        self.assertEqual(cfg.threshold_by_language, {})
        self.assertEqual(cfg.threshold_by_jurisdiction, {})

    def test_a_table_that_is_not_a_table_is_refused(self):
        with self.assertRaises(ConfigError):
            self._config("[retrieval]\nthreshold_by_language = 0.2\n")


# --------------------------------------------------------------------------
# What it does to an answer


class TestAnOverrideChangesOneSliceAndNoOther(DemoHarness):
    def test_an_arabic_override_changes_the_arabic_verdict(self):
        """The issue's first acceptance criterion. 0.69 is the measured
        Arabic score for this question on the demo corpus, so a ceiling above
        it turns the answer into a refusal and nothing else could have."""
        answered = ask(ARABIC, self.index, Config())
        refused = ask(ARABIC, self.index, Config(threshold_by_language={"ar": 0.95}))
        self.assertEqual(answered.answer.kind, "grounded")
        self.assertEqual(refused.answer.kind, "refusal")

    def test_and_no_other_language_moves(self):
        cfg = Config(threshold_by_language={"ar": 0.95})
        for question in (ENGLISH, SPANISH):
            with self.subTest(question=question):
                self.assertEqual(
                    ask(question, self.index, cfg).answer.cited_text,
                    ask(question, self.index, Config()).answer.cited_text,
                )

    def test_with_no_tables_every_answer_is_byte_identical(self):
        """`Config()` and a `Config` carrying empty tables are the same
        system, which is the claim the whole feature rests on."""
        for question in (ENGLISH, SPANISH, ARABIC, "What vaccinations does my dog need?"):
            with self.subTest(question=question):
                plain = ask(question, self.index, Config())
                tabled = ask(
                    question,
                    self.index,
                    Config(threshold_by_language={}, threshold_by_jurisdiction={}),
                )
                self.assertEqual(plain.answer.cited_text, tabled.answer.cited_text)
                self.assertEqual(
                    plain.answer.trace.threshold, tabled.answer.trace.threshold
                )
                self.assertEqual(
                    plain.answer.trace.threshold_key, "retrieval.threshold"
                )

    def test_the_language_key_is_the_language_answered_in_not_the_restriction(self):
        """The widened cross-language pass restricts to no language at all, so
        keying the override on the restriction would silently drop it exactly
        when the fallback fires. It is keyed on the language being answered
        in, which is the language whose band was measured."""
        cfg = Config(threshold_by_language={"es": 0.95})
        result = ask("GoPass", self.index, cfg, lang="es")
        for attempt in result.attempts:
            with self.subTest(scope=attempt.scope):
                self.assertEqual(
                    attempt.trace.threshold_key, "retrieval.threshold_by_language.es"
                )


class TestAJurisdictionOverrideIsResolvedPerRung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = layered_index()

    def test_each_rung_of_the_ladder_carries_its_own_key(self):
        """A `threshold_by_jurisdiction` entry is a statement about one
        layer's vocabulary, so it has to be resolved per pass and not once per
        question — the rungs are different layers."""
        cfg = Config(threshold_by_jurisdiction={"us-ca": 0.99})
        result = ask(
            "What is the countable income limit for a household of four?",
            self.index,
            cfg,
            jurisdiction=SONOMA,
        )
        keys = {a.jurisdiction: a.trace.threshold_key for a in result.attempts}
        self.assertEqual(keys["us-ca"], "retrieval.threshold_by_jurisdiction.us-ca")
        self.assertEqual(keys[SONOMA], "retrieval.threshold")
        self.assertEqual(keys["us"], "retrieval.threshold")

    def test_a_layer_ceiling_pushes_the_answer_outward(self):
        """The behavioural consequence: a layer whose threshold nothing can
        clear is a layer the ladder walks past, under the ordinary notice."""
        plain = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        self.assertEqual(plain.source_jurisdictions, (SONOMA,))
        raised = ask(
            HOURS,
            self.index,
            Config(threshold_by_jurisdiction={SONOMA: 0.99}),
            jurisdiction=SONOMA,
        )
        self.assertEqual(raised.source_jurisdictions, ("us-ca",))
        self.assertIn(SONOMA, raised.answer.notice)


class TestTheKeyReachesTheRetrievers(DemoHarness):
    def test_retrieve_records_what_it_was_told(self):
        trace = retrieve(
            ENGLISH, self.index, threshold=0.2, candidates=4, threshold_key="whatever"
        )
        self.assertEqual(trace.threshold_key, "whatever")

    def test_the_default_is_the_base_key_so_existing_callers_are_unchanged(self):
        trace = retrieve(ENGLISH, self.index, threshold=0.2, candidates=4)
        self.assertEqual(trace.threshold_key, "retrieval.threshold")

    def test_the_split_intents_merge_carries_it_through(self):
        merged = split_intents(
            "How much is the allowance, and when does it arrive?",
            self.index,
            threshold=0.165,
            candidates=8,
            lang="en",
            threshold_key="retrieval.threshold_by_language.en",
        )
        self.assertEqual(
            merged.threshold_key, "retrieval.threshold_by_language.en"
        )


# --------------------------------------------------------------------------
# Explain


class TestExplainNamesTheKey(DemoHarness):
    def _report(self, cfg: Config, question: str = ARABIC) -> str:
        result = ask(question, self.index, cfg)
        return render(
            result, diagnose(result.answer, max_passages=cfg.max_passages),
            index_summary="fixture",
        )

    def test_the_header_names_the_override_in_force(self):
        report = self._report(Config(threshold_by_language={"ar": 0.21}))
        self.assertIn("Threshold: 0.210 (retrieval.threshold_by_language.ar)", report)

    def test_the_header_names_the_base_key_when_no_override_applies(self):
        report = self._report(Config())
        self.assertIn("Threshold: 0.165 (retrieval.threshold)", report)

    def test_the_below_threshold_detail_names_it_too(self):
        """The header sits forty lines above the advice. An operator reading
        "none cleared the threshold" is about to go and raise one, and needs
        to be told which."""
        cfg = Config(threshold_by_language={"ar": 0.95})
        result = ask(ARABIC, self.index, cfg)
        detail = diagnose(result.answer, max_passages=1).stage("retrieval").detail
        self.assertIn("retrieval.threshold_by_language.ar", detail)

    def test_the_json_payload_carries_it(self):
        cfg = Config(threshold_by_language={"ar": 0.21})
        payload = trace_payload(ask(ARABIC, self.index, cfg).answer.trace)
        self.assertEqual(payload["threshold"], 0.21)
        self.assertEqual(
            payload["threshold_key"], "retrieval.threshold_by_language.ar"
        )

    def test_the_payload_always_carries_it_rather_than_omitting_the_default(self):
        """A consumer must never have to infer "the default was in force" from
        the absence of a field."""
        payload = trace_payload(ask(ENGLISH, self.index, Config()).answer.trace)
        self.assertEqual(payload["threshold_key"], "retrieval.threshold")


# --------------------------------------------------------------------------
# Calibration


class TestCalibrateReportsPerSlice(DemoHarness):
    def _report(self, cfg: Config | None = None):
        return calibrate(self.index, cfg or Config(), PROBES)

    def test_every_probe_records_the_threshold_that_gated_it(self):
        report = self._report(Config(threshold_by_language={"ar": 0.21}))
        arabic = [r for r in report.results if r.lang == "ar"]
        self.assertTrue(arabic)
        for probe in arabic:
            with self.subTest(question=probe.question):
                self.assertEqual(probe.threshold, 0.21)
                self.assertEqual(
                    probe.threshold_key, "retrieval.threshold_by_language.ar"
                )

    def test_slices_are_grouped_on_the_language_answered_in(self):
        """The bundled probe set labels its Spanish and Arabic probes and
        leaves the English ones to detection, exactly as `cairn ask` does.
        Grouping on the authored field put four English probes in no slice at
        all, and emitted a recommendation table with no `en` in it."""
        report = self._report()
        self.assertEqual(set(report.by_label("lang")), {"ar", "en", "es"})

    def test_a_slice_is_the_same_type_and_computes_its_own_band(self):
        report = self._report()
        arabic = report.by_label("lang")["ar"]
        self.assertEqual(len(arabic.results), 2)
        self.assertIsNotNone(arabic.gap)
        self.assertGreater(arabic.gap, 0)

    def test_an_unlayered_corpus_has_no_jurisdiction_slices(self):
        """Absence stays absence: a corpus with no layers must not produce a
        band for a placeholder layer."""
        self.assertEqual(self._report().by_label("jurisdiction"), {})

    def test_the_render_names_every_language_band(self):
        text = render_calibration(self._report())
        self.assertIn("By language:", text)
        for code in ("ar", "en", "es"):
            with self.subTest(code=code):
                self.assertIn(code, text)

    def test_the_header_says_when_probes_were_gated_by_different_keys(self):
        """One figure in the header would be the number that decided some of
        these rows and not others."""
        text = render_calibration(self._report(Config(threshold_by_language={"ar": 0.21})))
        self.assertIn("gated by 2 different keys", text)
        self.assertIn("retrieval.threshold_by_language.ar", text)

    def test_the_header_is_unchanged_when_one_key_gated_everything(self):
        text = render_calibration(self._report())
        self.assertIn("8 probe(s) against threshold 0.165", text)
        self.assertNotIn("different keys", text)


class TestEmitConfig(DemoHarness):
    def _emitted(self, cfg: Config | None = None) -> str:
        return emit_config(calibrate(self.index, cfg or Config(), PROBES))

    def test_it_emits_a_table_of_midpoints(self):
        emitted = self._emitted()
        self.assertIn("[retrieval.threshold_by_language]", emitted)
        for code in ("ar", "en", "es"):
            with self.subTest(code=code):
                self.assertIn(f'"{code}" = ', emitted)

    def test_what_it_emits_parses_as_toml_and_loads_as_a_config(self):
        """A recommendation an operator cannot paste is not a
        recommendation."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "cairn.toml"
        path.write_text(self._emitted(), encoding="utf-8")
        cfg = load_config(path)
        self.assertEqual(set(cfg.threshold_by_language), {"ar", "en", "es"})

    def test_the_midpoints_are_the_ones_the_report_computed(self):
        report = calibrate(self.index, Config(), PROBES)
        emitted = emit_config(report)
        for code, group in report.by_label("lang").items():
            with self.subTest(code=code):
                self.assertIn(f'"{code}" = {group.suggested_threshold:.3f}', emitted)

    @staticmethod
    def _probe(lang: str, behavior: str, score: float) -> ProbeResult:
        return ProbeResult(
            question=f"{lang} {behavior} {score}",
            behavior=behavior,
            lang=lang,
            jurisdiction=None,
            threshold=0.165,
            threshold_key="retrieval.threshold",
            top_score=score,
            outcome=behavior,
            correct=True,
        )

    def test_a_slice_with_no_separating_threshold_is_commented_not_dropped(self):
        """Dropping it leaves the operator reading a table that silently
        covers three of their four languages, and the missing one is the one
        that needs them.

        Built by hand rather than sliced out of the demo run, because the demo
        corpus separates cleanly in all three languages — a fixture that
        cannot reach the branch would leave this reading as a verified guard.
        """
        report = CalibrationReport(
            threshold=0.165,
            results=(
                self._probe("ar", "answer", 0.10),
                self._probe("ar", "refuse", 0.40),
                self._probe("en", "answer", 0.50),
                self._probe("en", "refuse", 0.05),
            ),
        )
        self.assertLessEqual(report.by_label("lang")["ar"].gap, 0)
        emitted = emit_config(report)
        self.assertIn("# ar = ?", emitted)
        self.assertIn("NO SEPARATING THRESHOLD", emitted)
        self.assertIn("nothing to recommend", emitted)
        self.assertIn('"en" = ', emitted)

    def test_a_slice_with_nothing_to_compare_is_commented_too(self):
        """"No refuse probes in this language" and "no threshold separates
        them" are different findings and both produce no recommendation. The
        comment says which."""
        report = CalibrationReport(
            threshold=0.165,
            results=(self._probe("ar", "answer", 0.5), self._probe("en", "refuse", 0.05)),
        )
        emitted = emit_config(report)
        self.assertIn("no band", emitted)
        self.assertNotIn("NO SEPARATING THRESHOLD", emitted)

    def test_it_says_in_the_output_that_nothing_was_applied(self):
        self.assertIn("Nothing has been", self._emitted())

    def test_it_never_writes_to_the_config(self):
        """Stated as a test rather than only as a docstring: a tool that
        edited `cairn.toml` would be making the operator's decision by being
        run."""
        before = Path("cairn.toml").read_bytes()
        self._emitted()
        self.assertEqual(Path("cairn.toml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
