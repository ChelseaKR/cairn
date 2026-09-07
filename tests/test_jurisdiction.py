"""Jurisdiction as a corpus dimension: scoping, widening, and disclosure.

The failure this feature exists to stop is one sentence long: a Sonoma
resident asking about office hours is answered from a Siskiyou page and
nothing says so. Everything here is that sentence taken apart —
:class:`TestTheWrongCountyNeverAnswers` is the sentence itself, and the rest
holds the pieces it stands on.

The fixture corpus is ``tests/layered.py``: four labelled layers, a sibling
county to be the wrong answer, and one deliberately unlabelled document.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from cairn.config import Config, ConfigError, load_config
from cairn.corpus import CorpusError, load_document
from cairn.engine import EngineError, ask, resolve_jurisdiction
from cairn.explain import diagnose, refusal_reason, render, trace_payload
from cairn.index import INDEX_FORMAT_VERSION, build_index, read_index, write_index
from cairn.jurisdiction import CODE, SEPARATOR, JurisdictionError, covers, ladder, validate
from cairn.messages import CATALOGUE
from cairn.receipt import RECEIPT_VERSION, Receipt, ReceiptError, receipt_for
from cairn.record import build_items_and_responses
from cairn.retrieve import retrieve
from cairn.ui.page import render_page
from tests.layered import DOCUMENTS, jurisdiction_corpus, layered_index

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"

SONOMA = "us-ca-sonoma"
HOURS = "What are the service counter hours?"
FEDERAL_ONLY = "What is the countable income limit for a household of four?"
TRANSPORT = "transport reimbursement mileage rate"
# Worded out of the Siskiyou page's own opening hours, so that page wins the
# whole corpus outright. Asked as Sonoma it must still be Sonoma's page that
# answers — which is the entire feature in one assertion, and an assertion
# that can fail, which `HOURS` alone turned out not to be: with scoping
# removed, `HOURS` is won by the *state* page, so "no Siskiyou id was cited"
# stayed true while the answer was wrong anyway.
SIBLING_WINS = "counter open ten in the morning until three"


class LayeredHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = layered_index()


# --------------------------------------------------------------------------
# The vocabulary


class TestTheCodeGrammar(unittest.TestCase):
    """The literals this module publishes, pinned as literals.

    A property test over "some well-formed code" cannot catch a separator
    changed from ``-`` to ``.`` or a pattern quietly widened to accept
    uppercase: both keep every property intact and change what a corpus
    written last week means. These constants are written into front matter,
    a config file, a query string and an HTML form value, so they are an
    interface and are pinned like one.
    """

    def test_the_separator_is_a_hyphen(self):
        self.assertEqual(SEPARATOR, "-")

    def test_the_pattern_is_exactly_this(self):
        self.assertEqual(CODE.pattern, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    def test_what_it_accepts(self):
        for code in ("us", "us-ca", "us-ca-sonoma", "us-ca-san-mateo", "x9"):
            with self.subTest(code=code):
                self.assertEqual(validate(code, where="test"), code)

    def test_what_it_refuses(self):
        for code in ("", "US-CA", "us_ca", "us--ca", "-us", "us-", "us ca", "us.ca"):
            with self.subTest(code=code):
                with self.assertRaises(JurisdictionError):
                    validate(code, where="test")


class TestTheLadder(unittest.TestCase):
    def test_it_runs_from_the_most_specific_outward(self):
        self.assertEqual(ladder("us-ca-sonoma"), ("us-ca-sonoma", "us-ca", "us"))

    def test_a_single_segment_is_its_own_ladder(self):
        self.assertEqual(ladder("us"), ("us",))

    def test_no_jurisdiction_is_one_unrestricted_pass(self):
        """The whole reason an unlayered corpus is untouched by this feature:
        the loop that widens runs exactly once and restricts nothing."""
        self.assertEqual(ladder(None), (None,))

    def test_a_multi_word_county_has_an_inert_middle_rung(self):
        """Documented rather than fixed. `us-ca-san` matches no document, so
        the rung costs one pass and changes no answer; the alternative is a
        second separator, which is a second thing to get wrong."""
        self.assertEqual(
            ladder("us-ca-san-mateo"), ("us-ca-san-mateo", "us-ca-san", "us-ca", "us")
        )


class TestContainmentIsBySegmentNotByString(unittest.TestCase):
    def test_a_layer_covers_itself_and_what_is_inside_it(self):
        self.assertTrue(covers("us", "us-ca"))
        self.assertTrue(covers("us-ca", "us-ca-sonoma"))
        self.assertTrue(covers("us-ca", "us-ca"))

    def test_it_does_not_cover_outward_or_sideways(self):
        self.assertFalse(covers("us-ca-sonoma", "us-ca"))
        self.assertFalse(covers("us-ca-sonoma", "us-ca-siskiyou"))

    def test_a_string_prefix_is_not_containment(self):
        """`us-ca` is a string prefix of `us-california` and covers none of
        it. A containment test built on `startswith` would claim a
        Californian rule for an unrelated jurisdiction that happened to
        spell its name that way."""
        self.assertTrue("us-california".startswith("us-ca"))
        self.assertFalse(covers("us-ca", "us-california"))


# --------------------------------------------------------------------------
# Front matter


class TestFrontMatter(unittest.TestCase):
    def _document(self, line: str) -> Path:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "doc.md"
        path.write_text(
            "---\nid: doc\ntitle: T\nlang: en\n" + line + "---\n\nBody text here.\n",
            encoding="utf-8",
        )
        return path

    def test_a_code_is_read_onto_the_document_and_every_passage(self):
        doc = load_document(self._document("jurisdiction: us-ca-sonoma\n"))
        self.assertEqual(doc.jurisdiction, SONOMA)
        self.assertTrue(all(p.jurisdiction == SONOMA for p in doc.passages))

    def test_absent_is_none_and_none_is_not_a_jurisdiction(self):
        doc = load_document(self._document(""))
        self.assertIsNone(doc.jurisdiction)

    def test_an_empty_value_is_absence_not_a_code(self):
        """`jurisdiction:` with nothing after it says the same thing as no
        line at all. Becoming the code `""` would give the document a layer
        no question can name and no other document shares."""
        self.assertIsNone(load_document(self._document("jurisdiction:\n")).jurisdiction)

    def test_a_malformed_code_fails_the_load(self):
        """Unlike `reviewed_at`, which is inert and validated by lint. This
        one decides what a question can reach, so a typo must not be a
        silently narrower corpus."""
        with self.assertRaises(CorpusError) as caught:
            load_document(self._document("jurisdiction: US_CA\n"))
        self.assertIn("jurisdiction", str(caught.exception))


# --------------------------------------------------------------------------
# The index


class TestTheIndexCarriesIt(LayeredHarness):
    def test_the_format_version_is_five(self):
        self.assertEqual(INDEX_FORMAT_VERSION, 5)

    def test_the_codes_are_reported(self):
        self.assertEqual(
            self.index.jurisdiction_codes,
            ("us", "us-ca", "us-ca-siskiyou", SONOMA),
        )

    def test_an_unlayered_corpus_reports_none(self):
        self.assertEqual(build_index(DEMO).jurisdiction_codes, ())

    def test_it_survives_a_round_trip(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        corpus = jurisdiction_corpus(directory / "corpus")
        path = directory / "index.json"
        write_index(build_index(corpus), path)
        loaded = read_index(path, corpus)
        self.assertEqual(
            {p.passage_id: p.jurisdiction for p in loaded.passages},
            {p.passage_id: p.jurisdiction for p in self.index.passages},
        )

    def test_a_corpus_without_the_field_serializes_the_key_nowhere(self):
        """The byte-identity claim, stated over the file rather than over a
        hash: a corpus that has not opted in must not gain a `"jurisdiction":
        null` on every passage, which would move every committed index and
        every idempotency check for a field nobody used."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "index.json"
        write_index(build_index(DEMO), path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(payload["passages"])
        for passage in payload["passages"]:
            self.assertNotIn("jurisdiction", passage)


# --------------------------------------------------------------------------
# Configuration


class TestTheConfigKeys(unittest.TestCase):
    def test_the_defaults_are_off_and_permissive(self):
        self.assertIsNone(Config().default_jurisdiction)
        self.assertTrue(Config().cross_jurisdiction_fallback)

    def test_a_malformed_default_is_refused_when_the_object_is_built(self):
        """At the constructor, not only in the loader. This is a reference
        implementation somebody imports; `Config(default_jurisdiction="")`
        would scope every question to a layer nothing can carry."""
        for value in ("", "US-CA", "us ca"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                Config(default_jurisdiction=value)

    def test_the_file_reads_both_keys(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "cairn.toml"
        path.write_text(
            "[jurisdiction]\ndefault = 'us-ca-sonoma'\n"
            "cross_jurisdiction_fallback = false\n",
            encoding="utf-8",
        )
        cfg = load_config(path)
        self.assertEqual(cfg.default_jurisdiction, SONOMA)
        self.assertFalse(cfg.cross_jurisdiction_fallback)

    def test_an_absent_section_leaves_the_defaults(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "cairn.toml"
        path.write_text("[corpus]\npath = 'corpus/demo'\n", encoding="utf-8")
        self.assertIsNone(load_config(path).default_jurisdiction)


# --------------------------------------------------------------------------
# Retrieval


class TestRetrievalScopesToOneLayer(LayeredHarness):
    def test_a_scoped_pass_scores_that_layer_and_nothing_else(self):
        trace = retrieve(
            HOURS, self.index, threshold=0.165, candidates=8, jurisdiction=SONOMA
        )
        self.assertTrue(trace.candidates)
        for candidate in trace.candidates:
            self.assertEqual(candidate.passage.jurisdiction, SONOMA)

    def test_the_restriction_is_reported_on_the_trace(self):
        trace = retrieve(
            HOURS, self.index, threshold=0.165, candidates=8, jurisdiction=SONOMA
        )
        self.assertEqual(trace.jurisdiction, SONOMA)
        self.assertEqual(trace.scoped + trace.excluded, self.index.passage_count)

    def test_an_unlabelled_passage_is_out_of_scope_and_counted_apart(self):
        """A document that never said where it applies has not said it
        applies here — and "excluded because it is another county's" and
        "excluded because nobody labelled it" are different findings for an
        operator, so they are two numbers."""
        trace = retrieve(
            TRANSPORT, self.index, threshold=0.165, candidates=8, jurisdiction=SONOMA
        )
        self.assertEqual(trace.candidates, ())
        unlabelled = sum(1 for p in self.index.passages if p.jurisdiction is None)
        self.assertEqual(trace.unlabelled, unlabelled)
        self.assertGreater(unlabelled, 0, "the fixture must hold an unlabelled document")

    def test_without_a_jurisdiction_nothing_is_excluded_for_one(self):
        trace = retrieve(TRANSPORT, self.index, threshold=0.165, candidates=8)
        self.assertIsNone(trace.jurisdiction)
        self.assertEqual(trace.unlabelled, 0)
        self.assertTrue(trace.candidates)


# --------------------------------------------------------------------------
# The engine: the issue's "Done when" list


class TestTheWrongCountyNeverAnswers(LayeredHarness):
    """The failure the whole feature exists to stop."""

    def test_a_county_question_is_answered_from_that_county(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual(result.source_jurisdictions, (SONOMA,))
        self.assertIsNone(result.answer.notice)
        self.assertFalse(result.cross_jurisdiction)

    def test_a_sibling_county_is_never_quoted(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        cited = [s.source_id for s in result.answer.sources]
        self.assertTrue(cited)
        self.assertNotIn("siskiyou", " ".join(cited))

    def test_the_sibling_wins_the_open_corpus_and_is_still_not_quoted(self):
        """The one that can actually fail, and the reason it is here.

        A negative control on the test above showed it staying green with
        jurisdiction scoping removed entirely: unscoped, `HOURS` is won by the
        *state* page, so "no Siskiyou id was cited" was true of a wrong answer.
        A fixture sitting where the failure is impossible reads as a verified
        guard, so this one puts the failure back within reach — the first
        assertion is the control, checked in the test rather than remembered
        from a run.
        """
        open_corpus = retrieve(SIBLING_WINS, self.index, threshold=0.165, candidates=8)
        self.assertEqual(
            open_corpus.candidates[0].passage.jurisdiction,
            "us-ca-siskiyou",
            "this fixture only tests anything while the sibling county's page "
            "outranks every other layer's on this question",
        )
        result = ask(SIBLING_WINS, self.index, Config(), jurisdiction=SONOMA)
        self.assertEqual(result.source_jurisdictions, (SONOMA,))
        self.assertIsNone(result.answer.notice)

    def test_the_sibling_county_holds_an_answer_that_would_have_been_wrong(self):
        """The negative half. Without the guard there is something for the
        engine to get wrong: asked as Siskiyou, the same question is answered
        from the Siskiyou page, so the test above is not passing because the
        corpus is too thin to fail."""
        result = ask(HOURS, self.index, Config(), jurisdiction="us-ca-siskiyou")
        self.assertEqual(
            [s.source_id for s in result.answer.sources], ["siskiyou-office-hours-en#1"]
        )


class TestWideningOutward(LayeredHarness):
    def test_a_wider_layer_answers_and_says_so(self):
        result = ask(FEDERAL_ONLY, self.index, Config(), jurisdiction=SONOMA)
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual(result.source_jurisdictions, ("us",))
        self.assertTrue(result.cross_jurisdiction)
        self.assertIn("us-ca-sonoma", result.answer.notice)
        self.assertIn(
            CATALOGUE["en"]["cross_jurisdiction_notice"].split("{")[0],
            result.answer.notice,
        )

    def test_it_widens_one_layer_at_a_time_from_the_most_specific(self):
        result = ask(FEDERAL_ONLY, self.index, Config(), jurisdiction=SONOMA)
        rungs = list(dict.fromkeys(a.jurisdiction for a in result.attempts))
        self.assertEqual(rungs, [SONOMA, "us-ca", "us"])

    def test_it_stops_at_the_first_layer_that_grounds(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        self.assertEqual([a.jurisdiction for a in result.attempts], [SONOMA])

    def test_it_never_widens_inward(self):
        """`us` has no office-hours page and three narrower layers do. A
        search that widened in either direction would answer this from a
        county's page for somebody who asked about the whole country."""
        result = ask(HOURS, self.index, Config(), jurisdiction="us")
        self.assertEqual(result.answer.kind, "refusal")

    def test_with_the_fallback_off_it_refuses_instead(self):
        result = ask(
            FEDERAL_ONLY,
            self.index,
            Config(cross_jurisdiction_fallback=False),
            jurisdiction=SONOMA,
        )
        self.assertEqual(result.answer.kind, "refusal")
        self.assertEqual(
            {a.jurisdiction for a in result.attempts},
            {SONOMA},
            "the ladder must not have been climbed at all",
        )

    def test_the_two_notices_compose_rather_than_replace(self):
        result = ask(
            FEDERAL_ONLY, self.index, Config(), lang="es", jurisdiction=SONOMA
        )
        self.assertTrue(result.cross_jurisdiction)
        self.assertTrue(result.cross_language)
        for key in ("cross_jurisdiction_notice", "cross_language_notice"):
            with self.subTest(key=key):
                self.assertIn(
                    CATALOGUE["es"][key].split("{")[0], result.answer.notice
                )

    def test_the_jurisdiction_half_is_said_first(self):
        """Which place's rule this is comes before which language it is
        written in: a reader who stops after one sentence has to have been
        told the more consequential thing."""
        result = ask(
            FEDERAL_ONLY, self.index, Config(), lang="es", jurisdiction=SONOMA
        )
        notice = result.answer.notice
        self.assertLess(
            notice.index(CATALOGUE["es"]["cross_jurisdiction_notice"].split("{")[0]),
            notice.index(CATALOGUE["es"]["cross_language_notice"].split("{")[0]),
        )


class TestARequestThatCannotBeHonoured(LayeredHarness):
    def test_a_corpus_with_no_layers_refuses_the_request(self):
        """Not ignored. Ignoring it answers from pages that never said where
        they apply and presents the result as the layer that was asked for."""
        with self.assertRaises(EngineError) as caught:
            ask(HOURS, build_index(DEMO), Config(), jurisdiction=SONOMA)
        self.assertIn("declares one", str(caught.exception))

    def test_a_malformed_code_is_refused(self):
        with self.assertRaises(EngineError):
            ask(HOURS, self.index, Config(), jurisdiction="US_CA")

    def test_a_layer_with_no_pages_of_its_own_is_not_refused(self):
        """The ordinary case, and the one an over-eager check would break: a
        county whose own material is not published yet still answers from the
        state layer under a notice."""
        result = ask(HOURS, self.index, Config(), jurisdiction="us-ca-yolo")
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual(result.source_jurisdictions, ("us-ca",))
        self.assertIn("us-ca-yolo", result.answer.notice)

    def test_the_flag_overrides_the_configured_default(self):
        cfg = Config(default_jurisdiction="us-ca-siskiyou")
        self.assertEqual(resolve_jurisdiction(self.index, cfg, None), "us-ca-siskiyou")
        self.assertEqual(resolve_jurisdiction(self.index, cfg, SONOMA), SONOMA)


class TestTheCountToolStandsDown(LayeredHarness):
    """A CSV table has no front matter to declare a jurisdiction in, so it
    has not said it applies here. A count over a statewide table handed to a
    county resident with nothing said is the same defect one path over."""

    def _index_with_a_table(self) -> tuple[Path, object]:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        corpus = jurisdiction_corpus(directory / "corpus")
        tables = corpus / "tables"
        tables.mkdir()
        (tables / "programs.csv").write_text(
            "# id: programs\n# title: Programs\n# lang: en\n# synthetic: true\n"
            "program,monthly_benefit\nHarbor nutrition,212\nHousing relief,448\n",
            encoding="utf-8",
        )
        return corpus, build_index(corpus)

    def test_the_tool_answers_when_no_jurisdiction_is_in_force(self):
        _, index = self._index_with_a_table()
        result = ask("How many programs have a monthly benefit over 100?", index, Config())
        self.assertIsNotNone(result.tool, "the fixture must bind the count tool")

    def test_the_tool_does_not_answer_under_a_jurisdiction(self):
        _, index = self._index_with_a_table()
        result = ask(
            "How many programs have a monthly benefit over 100?",
            index,
            Config(),
            jurisdiction=SONOMA,
        )
        self.assertIsNone(result.tool)


# --------------------------------------------------------------------------
# Explain


class TestExplainShowsTheLayerDecision(LayeredHarness):
    def _report(self, question: str, jurisdiction: str | None) -> str:
        result = ask(question, self.index, Config(), jurisdiction=jurisdiction)
        return render(
            result,
            diagnose(result.answer, max_passages=1),
            index_summary="fixture",
        )

    def test_it_names_the_layer_asked_about_and_the_widening(self):
        report = self._report(FEDERAL_ONLY, SONOMA)
        self.assertIn(f"Layer:     {SONOMA}", report)
        self.assertIn("widened through: us-ca-sonoma -> us-ca -> us", report)
        self.assertIn("answered from us, not us-ca-sonoma", report)

    def test_each_attempt_names_the_layer_it_searched(self):
        self.assertIn("layer 'us-ca'", self._report(FEDERAL_ONLY, SONOMA))

    def test_an_unlayered_run_prints_no_layer_lines(self):
        self.assertNotIn("Layer:", self._report(HOURS, None))

    def test_an_empty_layer_is_not_reported_as_an_empty_language(self):
        """The wrong diagnosis this branch replaced: `scoped == 0` reached
        the language wording and told an operator the corpus held nothing at
        all in English, for a corpus full of it."""
        trace = retrieve(
            HOURS, self.index, threshold=0.165, candidates=8,
            lang="en", jurisdiction="us-ca-yolo",
        )
        self.assertEqual(refusal_reason(trace), "no-passages-in-jurisdiction")
        detail = diagnose(
            ask(HOURS, self.index, Config(cross_jurisdiction_fallback=False),
                jurisdiction="us-ca-yolo").answer,
            max_passages=1,
        ).stage("retrieval").detail
        self.assertIn("us-ca-yolo", detail)
        self.assertNotIn("nothing at all in", detail)

    def test_the_json_payload_carries_the_layer(self):
        result = ask(FEDERAL_ONLY, self.index, Config(), jurisdiction=SONOMA)
        payload = trace_payload(result.answer.trace)
        self.assertEqual(payload["jurisdiction"], "us")
        self.assertEqual(payload["candidates"][0]["jurisdiction"], "us")

    def test_the_payload_is_unchanged_in_shape_for_an_unlayered_run(self):
        payload = trace_payload(ask(HOURS, build_index(DEMO), Config()).answer.trace)
        self.assertIsNone(payload["jurisdiction"])
        self.assertEqual(payload["unlabelled"], 0)


# --------------------------------------------------------------------------
# Receipts


class TestTheReceiptRecordsWhatWasAsked(LayeredHarness):
    def test_the_version_is_two(self):
        self.assertEqual(RECEIPT_VERSION, 2)

    def test_the_jurisdiction_is_part_of_the_document_and_its_digest(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        with_layer = receipt_for(
            result.answer, question=HOURS, corpus_fingerprint="a" * 64,
            cfg=Config(), jurisdiction=SONOMA,
        )
        without = receipt_for(
            result.answer, question=HOURS, corpus_fingerprint="a" * 64, cfg=Config()
        )
        self.assertEqual(with_layer.to_payload()["jurisdiction"], SONOMA)
        self.assertIsNone(without.to_payload()["jurisdiction"])
        self.assertNotEqual(with_layer.digest, without.digest)

    def test_it_round_trips(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        receipt = receipt_for(
            result.answer, question=HOURS, corpus_fingerprint="a" * 64,
            cfg=Config(), jurisdiction=SONOMA,
        )
        self.assertEqual(
            Receipt.from_payload(receipt.to_payload()).jurisdiction, SONOMA
        )

    def test_an_empty_string_is_refused_rather_than_read_as_absence(self):
        result = ask(HOURS, self.index, Config(), jurisdiction=SONOMA)
        payload = receipt_for(
            result.answer, question=HOURS, corpus_fingerprint="a" * 64,
            cfg=Config(), jurisdiction=SONOMA,
        ).to_payload()
        payload["jurisdiction"] = ""
        del payload["digest"]
        with self.assertRaises(ReceiptError):
            Receipt.from_payload(payload)


# --------------------------------------------------------------------------
# The recorder


class TestTheRecorderWritesTheAnsweringLayer(LayeredHarness):
    QUESTIONS = [
        {
            "id": "hours",
            "lang": "en",
            "behavior": "answer",
            "prompt": HOURS,
            "answering_sources": ["sonoma-office-hours-en.1"],
        },
        {
            "id": "federal",
            "lang": "en",
            "behavior": "answer",
            "prompt": FEDERAL_ONLY,
            "answering_sources": ["federal-eligibility-en.1"],
        },
        {
            "id": "nothing",
            "lang": "en",
            "behavior": "refuse",
            "prompt": "what is the airspeed of an unladen swallow",
        },
    ]

    def _items(self, questions=None, jurisdiction=SONOMA):
        items, _ = build_items_and_responses(
            self.index, Config(), questions or self.QUESTIONS,
            jurisdiction=jurisdiction,
        )
        return {item["id"]: item for item in items}

    def test_the_group_is_the_layer_that_answered(self):
        items = self._items()
        self.assertEqual(items["hours"]["group"], SONOMA)
        self.assertEqual(items["federal"]["group"], "us")

    def test_a_refusal_gets_no_group_rather_than_an_invented_one(self):
        """Absence stays absence: a `"none"` group would appear in the
        harness's disaggregation beside the real layers and be read as one."""
        self.assertNotIn("group", self._items()["nothing"])

    def test_an_authored_group_wins(self):
        questions = [{**self.QUESTIONS[0], "group": "hand-written"}]
        self.assertEqual(self._items(questions)["hours"]["group"], "hand-written")

    def test_an_unlayered_corpus_gains_no_group(self):
        """The byte-identical-bundle claim, at the level of the item the
        bundle is made of."""
        questions = [
            {
                "id": "grocery",
                "lang": "en",
                "behavior": "answer",
                "prompt": "How much is the monthly grocery allowance for one person?",
                "answering_sources": ["grocery-allowance-en.2"],
            }
        ]
        items, _ = build_items_and_responses(build_index(DEMO), Config(), questions)
        self.assertNotIn("group", items[0])


# --------------------------------------------------------------------------
# The served page


class TestTheServedSelector(LayeredHarness):
    def test_a_layered_deployment_gets_a_selector(self):
        page = render_page(
            "en", jurisdictions=self.index.jurisdiction_codes, jurisdiction=SONOMA
        )
        self.assertIn('<select id="jurisdiction" name="jurisdiction">', page)
        self.assertIn(f'<option value="{SONOMA}" selected>', page)
        for code in self.index.jurisdiction_codes:
            with self.subTest(code=code):
                self.assertIn(f'value="{code}"', page)

    def test_it_is_a_form_element_with_no_script_behind_it(self):
        page = render_page("en", jurisdictions=("us", "us-ca"), jurisdiction="us-ca")
        selector = page[page.index('id="jurisdiction"') :]
        self.assertNotIn("<script", selector[: selector.index("</select>")])

    def test_an_unlayered_deployment_gets_none(self):
        self.assertNotIn('name="jurisdiction"', render_page("en"))

    def test_a_single_layer_gets_none_either(self):
        """A control whose every choice is the same choice invites a person
        to believe they changed something."""
        self.assertNotIn('name="jurisdiction"', render_page("en", jurisdictions=("us",)))

    def test_the_selected_layer_is_offered_even_with_no_pages_of_its_own(self):
        page = render_page("en", jurisdictions=("us", "us-ca"), jurisdiction="us-ca-yolo")
        self.assertIn('<option value="us-ca-yolo" selected>', page)

    def test_every_language_can_label_it(self):
        for lang in CATALOGUE:
            with self.subTest(lang=lang):
                self.assertIn("jurisdiction_label", CATALOGUE[lang])


# --------------------------------------------------------------------------
# The fixture itself


class TestTheFixtureCanFail(LayeredHarness):
    """A corpus in which every question has the same answer everywhere would
    make every test above pass for the wrong reason."""

    def test_the_layers_hold_genuinely_different_text(self):
        hours = {
            jurisdiction: body
            for _, jurisdiction, _, _, _, body in DOCUMENTS
            if jurisdiction and "counter" in body
        }
        self.assertGreater(len(hours), 2)
        self.assertEqual(len(set(hours.values())), len(hours))

    def test_the_index_holds_the_layers_the_fixture_declares(self):
        declared = {j for _, j, _, _, _, _ in DOCUMENTS if j}
        self.assertEqual(set(self.index.jurisdiction_codes), declared)

    def test_ask_result_reports_the_layers_of_exactly_the_quoted_sources(self):
        result = ask(FEDERAL_ONLY, self.index, Config(max_passages=1), jurisdiction=SONOMA)
        self.assertEqual(
            len(result.source_jurisdictions), len(result.answer.sources)
        )

    def test_the_result_type_has_no_field_this_file_forgot(self):
        """Companion to tests/test_disclosure.py's version of this: that one
        asks whether a reader is told, this one asks whether the retrieval
        trace still carries the two fields the scoping depends on."""
        from cairn.retrieve import RetrievalTrace

        names = {f.name for f in fields(RetrievalTrace)}
        self.assertIn("jurisdiction", names)
        self.assertIn("unlabelled", names)


if __name__ == "__main__":
    unittest.main()
