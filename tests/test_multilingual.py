"""R4: three languages, one of them genuinely right-to-left.

"Genuinely" is the whole point of this file. Translated strings are the easy
half; these tests cover the half that is usually missing — direction derived
from the language, bidi isolation of Latin runs inside Arabic sentences,
script-aware tokenization, and an honest cross-language path when the corpus
has no source in the language someone asked in.
"""

import unittest
from pathlib import Path

from cairn.config import Config
from cairn.corpus import load_corpus
from cairn.engine import EngineError, ask, available_languages
from cairn.index import build_index
from cairn.language import (
    LANGUAGES,
    POP_DIRECTIONAL_ISOLATE,
    detect,
    direction_of,
    endonym_of,
    isolate,
)
from cairn.messages import CATALOGUE, DEFAULT_LANG, text
from cairn.text import dominant_script, normalize, tokenize

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CFG = Config()

QUESTIONS = {
    "en": "How much is the monthly grocery allowance for one person?",
    "es": "Cuanto recibe un hogar de una persona del subsidio de alimentos?",
    "ar": "كم تحصل الأسرة المكونة من شخص واحد شهريًا من مخصص البقالة؟",
}
# The transit pass exists only in English, on purpose (corpus/demo/README.md).
ENGLISH_ONLY_QUESTION = "How much does the GoPass cost per year?"


class MultilingualHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)

    def ask(self, question, cfg=CFG, **kwargs):
        return ask(question, self.index, cfg, **kwargs)


class TestCorpusCoverage(MultilingualHarness):
    def test_three_languages_one_of_them_rtl(self):
        langs = set(self.index.language_codes)
        self.assertGreaterEqual(len(langs), 3)
        rtl = {code for code in langs if direction_of(code) == "rtl"}
        self.assertTrue(rtl, "at least one corpus language must be right-to-left")
        self.assertIn("ar", rtl)

    def test_arabic_documents_are_arabic_script_and_synthetic(self):
        arabic = [d for d in load_corpus(DEMO) if d.lang == "ar"]
        self.assertGreaterEqual(len(arabic), 3)
        for doc in arabic:
            self.assertTrue(doc.synthetic)
            self.assertEqual(dominant_script(doc.title), "arabic")
            for passage in doc.passages:
                self.assertEqual(dominant_script(passage.text), "arabic")


class TestDirection(unittest.TestCase):
    def test_direction_comes_from_the_language_code(self):
        self.assertEqual(direction_of("ar"), "rtl")
        self.assertEqual(direction_of("he"), "rtl")
        self.assertEqual(direction_of("ar-EG"), "rtl", "subtags do not change direction")
        self.assertEqual(direction_of("en"), "ltr")
        self.assertEqual(direction_of("es"), "ltr")
        self.assertEqual(direction_of("qqq"), "ltr", "unknown codes default to ltr")

    def test_interface_languages_agree_with_the_direction_table(self):
        for code, language in LANGUAGES.items():
            self.assertEqual(language.direction, direction_of(code))

    def test_isolate_wraps_and_closes(self):
        wrapped = isolate("grocery-allowance-ar#2")
        self.assertTrue(wrapped.endswith(POP_DIRECTIONAL_ISOLATE))
        self.assertIn("grocery-allowance-ar#2", wrapped)
        self.assertNotEqual(wrapped, "grocery-allowance-ar#2")


class TestArabicTokenization(unittest.TestCase):
    def test_diacritics_do_not_split_words(self):
        self.assertEqual(tokenize("شهريًا"), tokenize("شهريا"))
        self.assertEqual(
            tokenize("تحصل الأسرة على $212 شهريًا"),
            ["تحصل", "اسره", "علي", "212", "شهريا"],
            "a diacritic must not break a word in two",
        )

    def test_alef_and_teh_marbuta_are_folded(self):
        self.assertEqual(normalize("الأسرة"), normalize("الاسره"))
        self.assertEqual(normalize("إغاثة"), normalize("اغاثه"))

    def test_the_definite_article_does_not_eat_the_stem(self):
        self.assertEqual(normalize("المساعدة"), normalize("مساعدة"))
        self.assertEqual(normalize("بالبريد"), normalize("بريد"))
        self.assertEqual(normalize("لمخصص"), normalize("مخصص"))

    def test_short_and_numeric_tokens(self):
        self.assertEqual(normalize("في"), "", "two-letter function words carry no signal")
        self.assertEqual(normalize("20"), "20", "numbers survive at any length")

    def test_latin_text_is_untouched_by_the_arabic_rules(self):
        self.assertEqual(tokenize("monthly grocery allowance"), ["month", "groce", "allow"])


class TestDetection(MultilingualHarness):
    def test_a_question_is_answered_in_the_language_it_was_asked_in(self):
        for lang, question in QUESTIONS.items():
            with self.subTest(lang=lang):
                result = self.ask(question)
                self.assertEqual(result.detection.lang, lang)
                self.assertEqual(result.answer.lang, lang)
                self.assertEqual(result.answer.direction, direction_of(lang))

    def test_same_language_sources_are_cited_when_the_corpus_has_them(self):
        for lang, question in QUESTIONS.items():
            with self.subTest(lang=lang):
                answer = self.ask(question).answer
                self.assertEqual(answer.kind, "grounded")
                self.assertTrue(all(s.lang == lang for s in answer.sources))
                self.assertFalse(self.ask(question).cross_language)

    def test_arabic_is_chosen_by_script_not_by_vocabulary(self):
        detection = detect("ما هي عاصمة فرنسا؟", self.index, default="en")
        self.assertEqual(detection.lang, "ar")
        self.assertEqual(detection.basis, "script")

    def test_an_unrecognizable_question_falls_back_to_the_configured_default(self):
        for question in ("", "zzzzqqqq wwwwxxxx"):
            with self.subTest(question=question):
                detection = detect(question, self.index, default="es")
                self.assertEqual(detection.lang, "es")
                self.assertEqual(detection.basis, "default")

    def test_an_explicit_request_always_wins(self):
        result = self.ask(QUESTIONS["en"], lang="ar")
        self.assertEqual(result.detection.basis, "requested")
        self.assertEqual(result.answer.lang, "ar")
        self.assertEqual(result.answer.direction, "rtl")

    def test_an_unsupported_language_is_refused_as_a_request_not_answered_badly(self):
        with self.assertRaises(EngineError):
            self.ask(QUESTIONS["en"], lang="tlh")

    def test_available_languages_include_every_interface_language(self):
        available = available_languages(self.index)
        self.assertLessEqual(set(LANGUAGES), set(available))


class TestCrossLanguageFallback(MultilingualHarness):
    def test_it_answers_from_another_language_and_says_so(self):
        result = self.ask(ENGLISH_ONLY_QUESTION, lang="es")
        answer = result.answer
        self.assertEqual(answer.kind, "grounded")
        self.assertEqual(answer.lang, "es")
        self.assertTrue(result.cross_language)
        self.assertTrue(all(s.lang == "en" for s in answer.sources))
        self.assertIsNotNone(answer.notice)
        self.assertIn(endonym_of("en"), answer.notice)
        self.assertIn("otro idioma", answer.notice, "the notice is in the answer language")

    def test_the_quoted_source_is_not_translated(self):
        answer = self.ask(ENGLISH_ONLY_QUESTION, lang="es").answer
        passages = {p.passage_id: p for p in self.index.passages}
        self.assertTrue(answer.sources, "a refusal here would empty this check")
        for source in answer.sources:
            self.assertIn(passages[source.source_id].text, answer.text)

    def test_the_notice_is_never_mixed_into_the_answer_text(self):
        answer = self.ask(ENGLISH_ONLY_QUESTION, lang="es").answer
        self.assertNotIn(answer.notice, answer.text)

    def test_the_plain_text_form_carries_the_notice(self):
        # `Answer.text` stays byte-for-byte corpus content and the notice
        # rides beside it in the structured payload, which is fine for any
        # client that can render two fields. `cited_text` is the form for the
        # clients that cannot — a terminal, an SMS gateway, a transcript — and
        # for them it is the entire answer. Dropping the notice there hands a
        # Spanish speaker an English passage with nothing saying why: the same
        # defect as an answer with no citations in it, one field over, and
        # that defect is why `cited_text` exists at all.
        answer = self.ask(ENGLISH_ONLY_QUESTION, lang="es").answer
        self.assertIsNotNone(answer.notice)
        self.assertTrue(
            answer.cited_text.startswith(answer.notice),
            "a text-only client is told the source is in another language first",
        )
        self.assertIn(answer.text, answer.cited_text, "the quote is still verbatim")
        self.assertEqual(answer.to_payload()["cited_text"], answer.cited_text)

    def test_the_command_line_says_the_same_thing_in_the_same_order(self):
        # Two renderers, one order. The CLI builds notice-then-quote itself;
        # if they ever disagree, one of them is telling somebody something the
        # other is not.
        from cairn.cli import _render_answer

        result = self.ask(ENGLISH_ONLY_QUESTION, lang="es")
        printed = _render_answer(result)
        self.assertLess(
            printed.index(result.answer.notice),
            printed.index(result.answer.text),
            "the notice leads in both forms",
        )

    def test_two_attempts_are_recorded_and_the_first_one_was_restricted(self):
        result = self.ask(ENGLISH_ONLY_QUESTION, lang="es")
        self.assertEqual([a.scope for a in result.attempts], ["language", "corpus"])
        self.assertEqual(result.attempts[0].trace.lang, "es")
        self.assertGreater(result.attempts[0].trace.excluded, 0)
        self.assertIsNone(result.attempts[1].trace.lang)

    def test_it_can_be_switched_off_in_favour_of_refusing(self):
        strict = Config(cross_language_fallback=False)
        result = self.ask(ENGLISH_ONLY_QUESTION, cfg=strict, lang="es")
        self.assertEqual(result.answer.kind, "refusal")
        self.assertEqual(len(result.attempts), 1)
        self.assertIsNone(result.answer.notice)

    def test_a_grounded_in_language_answer_never_widens(self):
        result = self.ask(QUESTIONS["ar"])
        self.assertEqual([a.scope for a in result.attempts], ["language"])


class TestLocalizedVoice(MultilingualHarness):
    def test_refusals_speak_the_language_of_the_question(self):
        refusals = {
            lang: self.ask("What vaccinations does my dog need?", lang=lang).answer.text
            for lang in ("en", "es", "ar")
        }
        self.assertNotEqual(refusals["en"], refusals["es"])
        self.assertNotEqual(refusals["en"], refusals["ar"])
        self.assertEqual(dominant_script(refusals["ar"]), "arabic")
        # Against the configured table, not against `contact_for` — which is
        # the same lookup with the same fallback, so both sides of the old
        # assertion moved together and an Arabic refusal ending in the English
        # contact line satisfied it. The point of a per-language contact is
        # that a person is pointed at help in a language they read.
        for lang, body in refusals.items():
            with self.subTest(lang=lang):
                configured = CFG.contact_by_language[lang]
                self.assertIn(configured.split(" (")[0][:20], body)
        self.assertEqual(dominant_script(CFG.contact_by_language["ar"]), "arabic")
        self.assertNotIn(CFG.contact_by_language["en"], refusals["ar"])

    def test_rtl_refusals_isolate_the_latin_contact_details(self):
        arabic = self.ask("What vaccinations does my dog need?", lang="ar").answer.text
        self.assertIn(POP_DIRECTIONAL_ISOLATE, arabic)
        english = self.ask("What vaccinations does my dog need?", lang="en").answer.text
        self.assertNotIn(POP_DIRECTIONAL_ISOLATE, english)

    def test_the_payload_states_language_and_direction(self):
        payload = self.ask(QUESTIONS["ar"]).answer.to_payload()
        self.assertEqual(payload["lang"], "ar")
        self.assertEqual(payload["dir"], "rtl")
        self.assertTrue(payload["sources"], "a refusal here would empty this check")
        for source in payload["sources"]:
            self.assertEqual(source["dir"], "rtl")


class TestMessageCatalogue(unittest.TestCase):
    def test_every_language_carries_every_key(self):
        reference = set(CATALOGUE[DEFAULT_LANG])
        for lang, catalogue in CATALOGUE.items():
            with self.subTest(lang=lang):
                self.assertEqual(set(catalogue), reference, "no language may miss a string")

    def test_no_translation_is_left_as_the_english_string(self):
        for lang, catalogue in CATALOGUE.items():
            if lang == DEFAULT_LANG:
                continue
            for key, value in catalogue.items():
                with self.subTest(lang=lang, key=key):
                    self.assertNotEqual(
                        value, CATALOGUE[DEFAULT_LANG][key], "untranslated string"
                    )

    def test_placeholders_match_across_languages(self):
        import string

        def fields(template):
            return {f for _, f, _, _ in string.Formatter().parse(template) if f}

        for key, reference in CATALOGUE[DEFAULT_LANG].items():
            for lang, catalogue in CATALOGUE.items():
                with self.subTest(lang=lang, key=key):
                    self.assertEqual(fields(catalogue[key]), fields(reference))

    def test_arabic_strings_are_actually_arabic(self):
        for key, value in CATALOGUE["ar"].items():
            with self.subTest(key=key):
                self.assertEqual(dominant_script(value), "arabic", f"{key} is not Arabic")

    def test_an_unknown_language_falls_back_rather_than_crashing(self):
        self.assertEqual(text("sources_heading", "qqq"), text("sources_heading", "en"))

    def test_an_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            text("no_such_message", "en")


class TestTheNoticeDescribesWhatIsActuallyQuoted(MultilingualHarness):
    """The notice is the one sentence standing between a reader and a passage
    they may not be able to read. It has to be true about the passages the
    answer contains, not about the search that found them."""

    def test_the_language_cairn_speaks_when_it_cannot_tell_is_bounded(self):
        # `language.default` decides the wording of every refusal and every
        # notice. It was unvalidated while both the edges around it — the
        # server's selector and the engine's explicit-language check — were
        # guarded, which is the same shape as the max_passages bug: the value
        # that skips both edges was the one nothing checked.
        # `Config(default_lang="fr")` produced a grounded answer labelled
        # `lang: "fr"` carrying an English cross-language notice, because the
        # message catalogue falls back to English for a code it cannot speak.
        from cairn.config import ConfigError

        for code in ("fr", "he", "xx", ""):
            with self.subTest(code=code), self.assertRaises(ConfigError):
                Config(default_lang=code)
        for code in LANGUAGES:
            with self.subTest(code=code):
                self.assertEqual(Config(default_lang=code).default_lang, code)

    def test_it_names_every_language_actually_quoted(self):
        # The notice used to read the first accepted passage's language while
        # composition quoted `max_passages` of them, so at 2 an Arabic reader
        # could be handed a Spanish passage and an English one under a notice
        # naming Spanish alone and calling it "the only source".
        result = ask("212", self.index, Config(max_passages=2), lang="ar")
        answer = result.answer
        quoted = {source.lang for source in answer.sources}
        self.assertEqual(quoted, {"es", "en"}, "this fixture needs two languages")
        for code in quoted:
            self.assertIn(endonym_of(code), answer.notice)

    def test_it_does_not_call_two_sources_the_only_one(self):
        one = ask("212", self.index, Config(max_passages=1), lang="ar").answer
        two = ask("212", self.index, Config(max_passages=2), lang="ar").answer
        self.assertEqual(one.notice, text(
            "cross_language_notice", "ar",
            language=isolate(endonym_of(one.sources[0].lang), rtl=True),
        ))
        self.assertNotEqual(one.notice, two.notice)
        self.assertEqual(dominant_script(two.notice), "arabic")

    def test_there_is_no_notice_when_nothing_foreign_was_quoted(self):
        for lang in ("en", "es", "ar"):
            with self.subTest(lang=lang):
                answer = ask(QUESTIONS[lang], self.index, CFG, lang=lang).answer
                self.assertEqual(answer.kind, "grounded")
                self.assertTrue(all(s.lang == lang for s in answer.sources))
                self.assertIsNone(answer.notice)

    def test_a_notice_and_a_foreign_source_always_travel_together(self):
        # The predicate used to be "the widened pass won", which implies
        # "quoted a foreign passage" only through a property of the scorer
        # that nothing states and nothing tests.
        for question in (ENGLISH_ONLY_QUESTION, "212", QUESTIONS["en"]):
            for lang in ("en", "es", "ar"):
                with self.subTest(question=question, lang=lang):
                    answer = ask(question, self.index, CFG, lang=lang).answer
                    foreign = any(s.lang != answer.lang for s in answer.sources)
                    self.assertEqual(foreign, answer.notice is not None)


class TestASmallLanguageIsStillARetrievableLanguage(unittest.TestCase):
    """The document-frequency floor used to delete a whole language.

    Every term in a language Cairn holds one passage of has
    ``df == passage_count``, so all of them clear ``df > 0.5 * N`` and the
    passage scores exactly 0.0 against every question in every language —
    including one that quotes it word for word. An agency that publishes one
    short translated notice, which is the realistic shape of a small language
    community's coverage, gets a document that is indexed, listed in
    `cairn index`'s language count, and unreachable.

    This was written up and left alone for a milestone on the grounds that no
    evidence item crossed languages. One does now (`ck-027`), which makes the
    cross-language fallback a path this repository publishes measurements
    about — and the fallback cannot rescue this case either, because it scores
    each passage against its own language's statistics.
    """

    ONE_PASSAGE = (
        "---\nid: flood-relief-vi\ntitle: Ho tro lu lut\nlang: vi\nsynthetic: true\n"
        "---\n\nChuong trinh ho tro lu lut tra toi da 4500 do la cho moi ho gia dinh.\n"
    )
    ASKED = "Chuong trinh ho tro lu lut tra bao nhieu tien?"

    def index_with(self, *documents: tuple[str, str]):
        import shutil
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        corpus = Path(tmp.name) / "corpus"
        shutil.copytree(DEMO, corpus)
        for name, body in documents:
            (corpus / name).write_text(body, encoding="utf-8")
        return build_index(corpus)

    def test_a_one_passage_language_can_be_reached(self):
        index = self.index_with(("flood-relief.vi.md", self.ONE_PASSAGE))
        self.assertEqual(index.stats_for("vi").passage_count, 1)
        result = ask(self.ASKED, index, Config())
        self.assertEqual(result.answer.kind, "grounded")
        self.assertEqual([s.source_id for s in result.answer.sources], ["flood-relief-vi#1"])
        self.assertEqual(result.answer.lang, "vi")

    def test_the_exemption_is_exactly_all_or_nothing(self):
        # The narrow claim. The floor is not softened for small languages; it
        # is skipped only where it would leave no term standing, which is the
        # case where it has stopped being a statistic and started being a
        # delete.
        index = self.index_with(("flood-relief.vi.md", self.ONE_PASSAGE))
        self.assertEqual(index.stats_for("vi").suppressed, frozenset())
        for code in ("en", "es", "ar"):
            with self.subTest(lang=code):
                stats = index.stats_for(code)
                suppressed = stats.suppressed
                self.assertTrue(suppressed, "the floor still does its job at scale")
                self.assertLess(len(suppressed), len(stats.doc_freq))
                for term in suppressed:
                    self.assertGreater(stats.doc_freq[term], 0.5 * stats.passage_count)
                for term, df in stats.doc_freq.items():
                    if term not in suppressed:
                        self.assertLessEqual(df, 0.5 * stats.passage_count)

    def test_it_does_not_pretend_to_fix_document_frequency_on_a_small_corpus(self):
        # The limitation as it actually is, so nobody reads the exemption as
        # more than it is: at two passages the floor bites again, and a term
        # in both of them — the program's own name, typically — is suppressed.
        two = self.ONE_PASSAGE + "\nDon xin phai duoc nop trong vong 30 ngay lu lut.\n"
        index = self.index_with(("flood-relief.vi.md", two))
        stats = index.stats_for("vi")
        self.assertEqual(stats.passage_count, 2)
        self.assertIn("lut", stats.suppressed, "in both passages, so suppressed")
        self.assertNotIn("4500", stats.suppressed, "in one, so it still scores")

    # Measured on the committed corpus after the exemption landed, and
    # identical to what the floor suppressed before it. Literals rather than
    # `{t for t, df in doc_freq.items() if df > cut}`, which is what stood
    # here for one draft: both sides of that comparison read `doc_freq` and
    # `passage_count` off the same object the implementation used, so an
    # off-by-one in document counting or a tokenizer change that merged two
    # terms moved both sides together and the check held while every
    # retrieval score in the corpus moved.
    SUPPRESSED = {
        "ar": ("هاربر",),
        "en": ("and", "harbo", "the"),
        "es": ("del", "harbo", "hogar", "los", "por", "que", "una"),
    }

    def test_the_demo_corpus_suppresses_exactly_what_it_did(self):
        # The exemption must be invisible to every language that has enough
        # passages for the floor to mean something, or it would have moved the
        # committed evidence. It did not: `cairn record` writes a
        # byte-identical bundle, and this is the same statement one level down,
        # where a term-by-term difference names itself.
        index = build_index(DEMO)
        self.assertEqual(set(index.language_codes), set(self.SUPPRESSED))
        for code, expected in self.SUPPRESSED.items():
            with self.subTest(lang=code):
                self.assertEqual(index.stats_for(code).suppressed, frozenset(expected))


if __name__ == "__main__":
    unittest.main()
