"""R6 + R7: the served interface, checked without a browser.

These are the checks that can be made from the markup and the stylesheet
alone: structure, semantics, language and direction, the contract of the two
live regions, and the contrast of every colour pair in both presentations.
The behaviors that only exist in a running browser — tab order, focus
visibility, announcements actually firing, the assertive channel staying quiet
on success — are driven against real Chromium in ``tests/browser/``.

Both layers matter. Markup checks catch a regression in a second and run
offline with no dependencies; the browser checks catch the things markup
cannot promise.
"""

import json
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from cairn.config import Config
from cairn.index import build_index
from cairn.language import direction_of
from cairn.messages import CATALOGUE
from cairn.server import CSP, STATIC, build_handler
from cairn.ui.contrast import PAIRS, palette
from cairn.ui.page import SELECTABLE

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")

FOCUSABLE = {"a", "button", "select", "textarea", "input"}


class Page(HTMLParser):
    """Just enough parsing to ask structural questions of the document."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.focusable = []  # (tag, attrs) in document order
        self.headings = []  # (level, text)
        self.elements = []  # (tag, attrs)
        self._heading = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        negative = attrs.get("tabindex", "").startswith("-")
        if (tag in FOCUSABLE and not negative) or (
            attrs.get("tabindex", "").lstrip("-").isdigit() and not negative
        ):
            if tag != "a" or "href" in attrs:
                self.focusable.append((tag, attrs))
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = (int(tag[1]), "")

    def handle_endtag(self, tag):
        if self._heading and re.fullmatch(r"h[1-6]", tag):
            self.headings.append(self._heading)
            self._heading = None

    def handle_data(self, data):
        if self._heading:
            self._heading = (self._heading[0], self._heading[1] + data)

    def find(self, tag, **match):
        for name, attrs in self.elements:
            if name == tag and all(attrs.get(k) == v for k, v in match.items()):
                return attrs
        return None

    def by_id(self, element_id):
        for _, attrs in self.elements:
            if attrs.get("id") == element_id:
                return attrs
        return None


def relative_luminance(colour):
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class ServerHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.index = build_index(DEMO)
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), build_handler(cls.cfg, cls.index, quiet=True)
        )
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path="/"):
        with urllib.request.urlopen(self.base + path) as response:
            return response, response.read().decode("utf-8")

    def post_json(self, payload):
        request = urllib.request.Request(
            self.base + "/ask",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_form(self, fields):
        request = urllib.request.Request(
            self.base + "/ask",
            data=urllib.parse.urlencode(fields).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")

    def page(self, path="/"):
        return Page(self.get(path)[1])


class TestDocumentStructure(ServerHarness):
    def test_document_declares_its_language_and_direction(self):
        for lang in SELECTABLE:
            with self.subTest(lang=lang):
                page = self.page(f"/?lang={lang}")
                html = page.find("html")
                self.assertEqual(html["lang"], lang)
                self.assertEqual(html["dir"], direction_of(lang))

    def test_an_unknown_language_falls_back_instead_of_serving_a_broken_page(self):
        page = self.page("/?lang=tlh")
        self.assertEqual(page.find("html")["lang"], self.cfg.default_lang)

    def test_the_skip_link_is_the_first_focusable_element(self):
        page = self.page()
        tag, attrs = page.focusable[0]
        self.assertEqual(tag, "a")
        self.assertEqual(attrs["href"], "#question")
        self.assertTrue(page.by_id("question"), "the skip link must land somewhere")

    def test_headings_start_at_one_and_never_skip_a_level(self):
        page = self.page()
        levels = [level for level, _ in page.headings]
        self.assertEqual(levels[0], 1)
        self.assertEqual(levels.count(1), 1, "exactly one h1")
        for previous, current in zip(levels, levels[1:], strict=False):
            self.assertLessEqual(current - previous, 1, f"skipped level: {levels}")

    def test_the_transcript_is_an_announced_log_that_can_be_reached(self):
        transcript = self.page().by_id("transcript")
        self.assertEqual(transcript["role"], "log")
        self.assertEqual(transcript["aria-live"], "polite")
        self.assertIn("aria-labelledby", transcript, "the log region needs a name")
        self.assertEqual(transcript["tabindex"], "0", "a scrollable region must be reachable")

    def test_the_only_assertive_region_is_the_error_channel(self):
        markup = self.get()[1]
        page = Page(markup)
        errors = page.by_id("errors")
        self.assertEqual(errors["role"], "alert")
        self.assertNotIn(
            'aria-live="assertive"',
            markup.replace('id="errors"', ""),
            "nothing but the error channel may interrupt",
        )
        self.assertEqual(page.by_id("status")["role"], "status")
        self.assertRegex(markup, r'id="errors"[^>]*></div>', "no error is present on load")

    def test_the_input_is_labelled_and_the_key_behaviour_is_written_down(self):
        page = self.page()
        self.assertEqual(page.find("label", **{"for": "question"})["for"], "question")
        textarea = page.by_id("question")
        self.assertEqual(textarea["aria-describedby"], "question-hint")
        hint = CATALOGUE["en"]["input_hint"]
        self.assertIn("Enter", hint)
        self.assertIn("Shift", hint)
        self.assertIn(hint, self.get()[1])

    def test_the_send_control_states_its_action(self):
        markup = self.get()[1]
        self.assertIn(f">{CATALOGUE['en']['send_button']}</button>", markup)
        self.assertNotIn(">Go</button>", markup)

    def test_the_language_selector_is_labelled_and_marks_each_option(self):
        page = self.page()
        self.assertEqual(page.find("label", **{"for": "lang"})["for"], "lang")
        options = [a for t, a in page.elements if t == "option"]
        self.assertEqual([o["value"] for o in options], list(SELECTABLE))
        for option in options:
            self.assertEqual(option["lang"], option["value"])
            self.assertEqual(option["dir"], direction_of(option["value"]))


class TestDisclosure(ServerHarness):
    def test_it_is_present_and_says_the_four_things(self):
        for lang in SELECTABLE:
            with self.subTest(lang=lang):
                markup = self.get(f"/?lang={lang}")[1]
                for key in (
                    "disclosure_ai",
                    "disclosure_sources",
                    "disclosure_limits",
                    "disclosure_synthetic",
                ):
                    self.assertIn(CATALOGUE[lang][key], markup)

    def test_it_cannot_be_dismissed(self):
        markup = self.get()[1]
        disclosure = markup.split('class="disclosure"')[1].split("</section>")[0]
        for dismissable in ("<button", "hidden", "aria-expanded", "<details"):
            self.assertNotIn(dismissable, disclosure)

    def test_it_comes_before_the_conversation_and_the_form(self):
        markup = self.get()[1]
        self.assertLess(markup.index("disclosure-heading"), markup.index('id="transcript"'))
        self.assertLess(markup.index("disclosure-heading"), markup.index('id="ask"'))


class TestTheInterfaceHasItsVoiceBeforeItFetchesAnything(ServerHarness):
    """A live region can only announce what is in it.

    The announcements used to arrive with ``/strings.json``, so until that
    response landed every call to the script's ``say()`` returned the empty
    string and the interface announced nothing — silently, in the two places
    (answer completion, request failure) where it promises to speak, and
    permanently if the fetch failed. The page now carries the language it was
    rendered in.
    """

    # The strings that are an announcement rather than a label: if any of
    # these is missing, something the interface says out loud is not said.
    SPOKEN = (
        "status_working",
        "status_answered",
        "status_refused",
        "error_request_failed",
        "error_empty_question",
    )

    def embedded(self, path="/"):
        body = self.get(path)[1]
        self.assertIn('id="ui-strings"', body, "the page carries no strings of its own")
        block = body.split('id="ui-strings">', 1)[1].split("</script>", 1)[0]
        return json.loads(block)

    def test_every_page_carries_the_language_it_was_rendered_in(self):
        for lang in SELECTABLE:
            with self.subTest(lang=lang):
                table = self.embedded(f"/?lang={lang}")
                for key in self.SPOKEN:
                    self.assertEqual(table.get(key), CATALOGUE[lang][key])

    def test_the_arabic_page_carries_arabic_and_not_a_fallback(self):
        table = self.embedded("/?lang=ar")
        self.assertNotEqual(table["status_refused"], CATALOGUE["en"]["status_refused"])

    def test_it_is_data_not_executable_script(self):
        # `default-src 'none'` forbids fetching script; a JSON block is not
        # script, so embedding one does not soften the policy.
        body = self.get()[1]
        self.assertIn('<script type="application/json" id="ui-strings">', body)
        self.assertEqual(
            self.get()[0].headers["Content-Security-Policy"], CSP
        )

    def test_no_catalogue_entry_could_close_the_element_early(self):
        for lang in SELECTABLE:
            with self.subTest(lang=lang):
                block = self.get(f"/?lang={lang}")[1].split('id="ui-strings">', 1)[1]
                self.assertNotIn("<", block.split("</script>", 1)[0])

    def test_the_script_reads_it_rather_than_waiting_for_the_fetch(self):
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        head = script.split("function say(", 1)[0]
        self.assertIn("ui-strings", head, "the script must have its voice before it speaks")
        self.assertNotIn(
            "strings = null", script,
            "an unloaded catalogue announces the empty string, which announces nothing",
        )


class TestOfflineAndPolicy(ServerHarness):
    def test_the_page_references_no_external_resource(self):
        for path in ("/", "/app.css", "/app.js"):
            with self.subTest(path=path):
                body = self.get(path)[1]
                self.assertNotIn("http://", body)
                self.assertNotIn("https://", body)
                self.assertNotIn("//cdn", body)

    def test_the_content_security_policy_forbids_going_off_origin(self):
        response = self.get()[0]
        policy = response.headers["Content-Security-Policy"]
        self.assertEqual(policy, CSP)
        self.assertIn("default-src 'none'", policy)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_unknown_routes_are_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get("/../cairn.toml")
        self.assertEqual(raised.exception.code, 404)


class TestAnswering(ServerHarness):
    def test_a_grounded_answer_comes_back_with_sources(self):
        payload = self.post_json(
            {"question": "How much is the monthly grocery allowance?", "lang": "en"}
        )
        self.assertEqual(payload["kind"], "grounded")
        self.assertIn("$212", payload["text"])
        self.assertTrue(payload["sources"])
        self.assertEqual(payload["lang"], "en")
        self.assertEqual(payload["dir"], "ltr")

    def test_a_refusal_comes_back_as_a_refusal_not_an_error(self):
        payload = self.post_json({"question": "Is the library open?", "lang": "en"})
        self.assertEqual(payload["kind"], "refusal")
        self.assertEqual(payload["sources"], [])

    def test_an_empty_question_is_rejected_before_the_engine_sees_it(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json({"question": "   ", "lang": "en"})
        self.assertEqual(raised.exception.code, 400)

    def test_the_interface_answers_identically_to_the_command_line(self):
        from cairn.engine import ask

        question = "Cuanto cubre la subvencion de alivio de vivienda?"
        served = self.post_json({"question": question, "lang": "es"})
        local = ask(question, self.index, self.cfg, lang="es").answer.to_payload()
        self.assertEqual(served, local, "one engine, one answer")


class TestWithoutJavaScript(ServerHarness):
    def test_the_form_alone_produces_a_rendered_answer(self):
        markup = self.post_form(
            {"question": "How much is the monthly grocery allowance?", "lang": "en"}
        )
        self.assertIn("turn-answered", markup)
        self.assertIn("$212", markup)
        self.assertIn("<bdi>grocery-allowance-en#2</bdi>", markup)

    def test_the_rendered_answer_keeps_every_word_of_the_source(self):
        from cairn.engine import ask

        question = "How much is the monthly grocery allowance?"
        markup = self.post_form({"question": question, "lang": "en"})
        answer = ask(question, self.index, self.cfg, lang="en").answer
        rendered = re.sub(r"<[^>]+>", "", markup)
        for line in answer.text.splitlines():
            words = line.lstrip("# ").strip()
            if words:
                self.assertIn(words, rendered, "only markup is dropped, never words")


class TestRightToLeftRendering(ServerHarness):
    def test_an_arabic_session_flips_the_document(self):
        markup = self.post_form({"question": "كم تحصل الأسرة شهريًا؟", "lang": "ar"})
        self.assertIn('<html lang="ar" dir="rtl">', markup)
        self.assertIn('class="answer" lang="ar" dir="rtl"', markup)

    def test_an_english_quote_in_an_arabic_page_keeps_its_own_language(self):
        # The bug this exists to catch: labelling the quote with the language
        # of the conversation, so a screen reader reads English in an Arabic
        # voice and the browser lays it out backwards.
        markup = self.post_form(
            {"question": "How much does the GoPass cost per year?", "lang": "ar"}
        )
        self.assertIn('<html lang="ar" dir="rtl">', markup)
        self.assertIn('class="notice" lang="ar" dir="rtl"', markup)
        self.assertIn('class="answer" lang="en" dir="ltr"', markup)
        self.assertNotIn('class="answer" lang="ar"', markup)

    def test_an_arabic_script_question_about_an_english_only_document_refuses(self):
        # Cross-language fallback is lexical, so it cannot cross scripts. The
        # honest outcome is a refusal, in Arabic, in a right-to-left page.
        markup = self.post_form(
            {"question": "كم تكلفة بطاقة جوباس السنوية؟", "lang": "ar"}
        )
        self.assertIn('<html lang="ar" dir="rtl">', markup)
        self.assertIn("turn-refusal", markup)
        self.assertIn('class="answer" lang="ar" dir="rtl"', markup)
        self.assertNotIn("<bdi>", markup, "a refusal cites nothing")

    def test_latin_identifiers_are_bidi_isolated(self):
        markup = self.post_form({"question": "كم تحصل الأسرة شهريًا؟", "lang": "ar"})
        self.assertRegex(markup, r"<bdi>[a-z-]+-ar#\d+</bdi>")


class TestStylesheet(unittest.TestCase):
    def test_layout_uses_logical_properties_so_rtl_mirrors(self):
        physical = re.findall(
            r"\b(margin|padding|border)-(left|right)\b|text-align:\s*(left|right)\b", CSS
        )
        self.assertEqual(physical, [], "physical sides do not flip for right-to-left")

    def test_both_presentations_are_defined(self):
        self.assertIn("@media (prefers-color-scheme: dark)", CSS)
        self.assertTrue(palette("light"))
        self.assertNotEqual(palette("light"), palette("dark"))

    def test_every_colour_pair_passes_contrast_in_both_presentations(self):
        # The same list of pairs an evidence bundle's interface snapshot
        # declares, so the auditor and this suite cannot disagree about which
        # colours the page uses.
        minimum = {"normal": 4.5, "large": 3.0}
        for scheme in ("light", "dark"):
            tokens = palette(scheme)
            for name, foreground, background, size in PAIRS:
                with self.subTest(scheme=scheme, pair=name):
                    ratio = contrast(tokens[foreground], tokens[background])
                    self.assertGreaterEqual(ratio, minimum[size], f"{ratio:.2f}:1")

    def test_focus_is_never_removed_without_being_put_back(self):
        self.assertIn(":focus-visible", CSS)
        self.assertNotIn("outline: none", CSS)
        self.assertNotIn("outline:none", CSS)

    def test_controls_clear_the_minimum_target_size(self):
        for rule in re.findall(r"min-height:\s*([\d.]+)rem", CSS):
            self.assertGreaterEqual(float(rule) * 16, 24, "WCAG 2.2 target size minimum")


if __name__ == "__main__":
    unittest.main()
