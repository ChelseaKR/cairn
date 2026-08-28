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
from html import escape, unescape
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from cairn.config import Config
from cairn.corpus import load_corpus
from cairn.index import build_index
from cairn.language import direction_of
from cairn.messages import CATALOGUE
from cairn.server import CSP, STATIC, build_handler
from cairn.ui import page
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

    def test_the_selector_offers_every_language_the_interface_speaks(self):
        """`SELECTABLE` decides two things, and the second one is not obvious.

        It fills the dropdown, and `cairn/server.py`'s `_resolve_lang` reads
        it to decide whether a requested `lang` is real, falling back to the
        configured default when it is not. A hand-kept tuple that fell behind
        `LANGUAGES` therefore did not merely hide an option: it made the
        served engine answer a French question in English, silently, while
        `cairn ask --lang fr` answered it in French. Derived now, and held
        here so the two cannot part again.
        """
        from cairn.language import LANGUAGES

        self.assertEqual(SELECTABLE, tuple(LANGUAGES))
        for code in SELECTABLE:
            with self.subTest(lang=code):
                self.assertIn(code, CATALOGUE, "a selectable language must speak")

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
        # The force of this check is the scoping: `ui-strings` has to be read
        # *before* `say()` is defined. `str.split` on a separator that is not
        # there returns the whole string, so renaming `say` — or reformatting
        # it to `function say (` — quietly turned the check into "the file
        # mentions ui-strings somewhere", which the fetch callback would also
        # satisfy. That is the regression the class docstring is about.
        self.assertIn("function say(", script, "the anchor this check scopes on is gone")
        head = script.split("function say(", 1)[0]
        self.assertIn("ui-strings", head, "the script must have its voice before it speaks")
        self.assertNotIn(
            "strings = null", script,
            "an unloaded catalogue announces the empty string, which announces nothing",
        )


class TestTheRequestItselfIsHandledSafely(ServerHarness):
    """The server speaks HTTP/1.1, so a client may put two requests on one
    socket. What it must never do is answer the second one with something
    derived from the first."""

    def raw(self, payload: bytes) -> bytes:
        import socket
        import time

        host, port = self.httpd.server_address[:2]
        sock = socket.create_connection((host, port), timeout=5)
        try:
            sock.sendall(payload)
            time.sleep(0.3)
            sock.settimeout(1.0)
            out = b""
            try:
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    out += chunk
            except OSError:
                pass
            return out
        finally:
            sock.close()

    def test_an_oversized_body_does_not_become_the_next_request(self):
        # It used to. An oversized body was refused by returning b"" without
        # reading it, so the unread bytes were parsed as the next request
        # line: a client that pipelined a real question behind an oversized
        # one got back `501 Unsupported method ('question=aaaa...')` and never
        # got its answer. The question went into the server's log on the way
        # past, on a server whose docstring says it logs nothing about the
        # questions people ask.
        oversized = b"a" * 9000
        first = (
            b"POST /ask HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: " + str(len(oversized)).encode() + b"\r\n\r\n" + oversized
        )
        body = b'{"question":"212","lang":"en"}'
        second = (
            b"POST /ask HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        out = self.raw(first + second)
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])
        self.assertNotIn(b"501", out)
        self.assertNotIn(b"Unsupported method", out)

    def test_a_content_length_that_is_not_a_number_is_a_bad_request(self):
        # It raised ValueError out of the read, which killed the handler
        # thread with a traceback and gave the client nothing at all.
        out = self.raw(b"POST /ask HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])
        # And the server is still answering afterwards.
        self.assertEqual(self.post_json({"question": "212", "lang": "en"})["lang"], "en")


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


class TestCopyExportControl(ServerHarness):
    """A read-only, always-visible way to get a grounded answer out of the
    page with its citations intact — no JavaScript required. See
    `cairn/ui/page.py`, `_copy_export`."""

    def test_a_grounded_answer_gets_a_copy_export_control(self):
        markup = self.post_form(
            {"question": "How much is the monthly grocery allowance?", "lang": "en"}
        )
        self.assertIn('<details class="copy-answer">', markup)
        self.assertIn("<summary>", markup)
        self.assertIn("Copy answer text", markup)
        self.assertIn("<textarea readonly", markup)
        self.assertIn('aria-label="Copy answer text"', markup)

    def test_a_refusal_gets_no_copy_export_control(self):
        markup = self.post_form({"question": "Is the library open?", "lang": "en"})
        self.assertNotIn("copy-answer", markup)
        self.assertNotIn("<textarea readonly", markup)

    def test_the_textarea_carries_the_full_cited_text_verbatim(self):
        from cairn.engine import ask

        question = "How much is the monthly grocery allowance?"
        markup = self.post_form({"question": question, "lang": "en"})
        answer = ask(question, self.index, self.cfg, lang="en").answer
        match = re.search(r"<textarea readonly[^>]*>(.*?)</textarea>", markup, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(unescape(match.group(1)), answer.cited_text)
        self.assertIn("[grocery-allowance-en.2]", unescape(match.group(1)))

    def test_the_control_mints_no_id_that_could_collide_across_turns(self):
        # `aria-label` labels the textarea instead of a `<label for>`, on
        # purpose: the server is stateless and the client script accumulates
        # turns into one page (cairn/ui/static/app.js), so an id minted here
        # would repeat every time a second grounded answer joins the
        # transcript. This checks the one turn this stateless server ever
        # renders at once carries none at all.
        markup = self.post_form(
            {"question": "How much is the monthly grocery allowance?", "lang": "en"}
        )
        start = markup.index('<details class="copy-answer">')
        block = markup[start : markup.index("</details>")]
        self.assertNotIn(" id=", block)


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


class TestQuotedCorpusText(unittest.TestCase):
    """Markup is removed, words are not — and both renderers agree on which.

    The page is built twice: by `cairn/ui/page.py` for the no-JavaScript POST,
    and by `cairn/ui/static/app.js` for the live transcript. They have to
    produce the same thing, and for one shape they did not. `_quoted_block`
    stripped `#` from the front of the raw line, so a heading with any
    indentation in front of it kept its `##` and rendered the marker as text,
    while the script — which strips the whitespace first — dropped it. No
    document in the demo corpus is indented, so nothing caught it; the claim
    in the docstring was that markup is removed, and for that line it was not.
    """

    CASES = (
        ("## How much the grant covers", "<strong>How much the grant covers</strong>"),
        ("  ## Indented heading", "<strong>Indented heading</strong>"),
        ("\t# Tab-indented", "<strong>Tab-indented</strong>"),
        ("### Trailing hashes ###", "<strong>Trailing hashes ###</strong>"),
        # Trailing whitespace is not a marker, so it survives — in both
        # renderers. The old rule dropped it, which was the smaller half of
        # the same disagreement.
        ("## Padded   ", "<strong>Padded   </strong>"),
        ("A sentence with a # in it", "A sentence with a # in it"),
        ("###", "###"),
        ("  ", "  "),
        ("", ""),
    )

    def test_the_marker_is_dropped_and_the_words_are_not(self):
        for line, expected in self.CASES:
            with self.subTest(line=line):
                self.assertEqual(page._quoted_block(line), expected)

    def test_no_rendered_heading_still_carries_its_marker(self):
        rendered = page._quoted_block("\n".join(line for line, _ in self.CASES))
        emphasized = re.findall(r"<strong>(.*?)</strong>", rendered)
        # The population first. `findall` returns [] when nothing is
        # emphasized at all, and "no heading kept its marker" is then true
        # because no heading was rendered — a `_quoted_block` that stopped
        # recognising headings entirely would pass this.
        self.assertEqual(
            len(emphasized),
            sum(1 for _, expected in self.CASES if "<strong>" in expected),
            "the cases that should render as headings did not",
        )
        for fragment in emphasized:
            self.assertFalse(
                fragment.lstrip().startswith("#"),
                f"an emphasized heading kept its marker: {fragment!r}",
            )

    def test_the_client_script_spells_the_same_two_rules(self):
        # Not "both look reasonable": the same two patterns, character for
        # character. Change one and this names the other.
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        for pattern in (page.ATX_LINE, page.ATX_MARKER):
            with self.subTest(pattern=pattern.pattern):
                self.assertIn(
                    f"/{pattern.pattern}/", script,
                    "app.js and page.py no longer agree on what a heading is",
                )

    def test_both_renderers_split_lines_the_same_way(self):
        # The other half of the algorithm, and the half the parity check above
        # cannot see. `str.splitlines()` breaks on U+2028, form feed, vertical
        # tab and U+0085 as well as on newlines, and rejoining with "\n" wrote
        # those characters out of the text — so a passage from a Word or PDF
        # extraction rendered on the server as something the cited source does
        # not say, while the same answer rendered client-side kept it. Both
        # sides split on "\n" and nothing else now.
        self.assertIn('body.split("\\n")', (STATIC / "app.js").read_text(encoding="utf-8"))
        for separator in (" ", " ", "\x0b", "\x0c", "\x85"):
            with self.subTest(separator=repr(separator)):
                body = f"pay $250{separator}per month"
                self.assertIn(escape(body), page._quoted_block(body))

    def test_a_hash_that_is_not_a_heading_keeps_its_hash(self):
        # CommonMark opens an ATX heading only when whitespace or the end of
        # the line follows the run of hashes, and at most six of them. The old
        # rule was "the line starts with #", which deleted a character of
        # somebody's benefit information: `#1 priority is rent` rendered as
        # **1 priority is rent**. Both tests that covered headings built their
        # expected value by running ATX_MARKER over the input, so the bug was
        # the specification and neither could fail.
        for line in ("#1 priority is rent", "#4 bus route runs hourly", "#hashtag"):
            with self.subTest(line=line):
                self.assertIn(escape(line), page._quoted_block(line))
                self.assertNotIn("<strong>", page._quoted_block(line))
        for line in ("# Heading", "###### Six", "  ## Indented"):
            with self.subTest(line=line):
                self.assertIn("<strong>", page._quoted_block(line))
        # Seven is not a heading in Markdown either.
        self.assertNotIn("<strong>", page._quoted_block("####### Seven"))

    def test_every_corpus_heading_survives_both_rules_the_same_way(self):
        # The parity check above is on the rule; this is on the content the
        # rule is actually applied to.
        #
        # The expected value is NOT `ATX_MARKER.sub("", line)`, which is what
        # stood here and is the third instance of the defect the docstring two
        # methods up describes: computing what should come out by running the
        # substitution under test over what went in, so both sides move
        # together and the specification becomes whatever the code does.
        # Measured: widen ATX_MARKER from `^\s*#+\s*` to `^\s*#+\s*.?` — a
        # plausible edit while tuning trailing hashes — and every corpus
        # heading renders with its first letter deleted, so a grounded answer
        # quotes something the cited passage does not say, and the old version
        # of this test passed.
        #
        # The rule here is one the renderer does not own: a whitespace-
        # separated token that is not made only of hashes is a word, and a
        # renderer that only removes markup cannot lose a word.
        emphasized = 0
        for document in load_corpus(DEMO):
            for passage in document.passages:
                with self.subTest(passage=passage.passage_id):
                    rendered = page._quoted_block(passage.text)
                    emphasized += rendered.count("<strong>")
                    self.assertNotIn("<strong>#", rendered)
                    for line in passage.text.splitlines():
                        for word in line.split():
                            if set(word) == {"#"}:
                                continue
                            self.assertIn(escape(word), rendered, f"lost {word!r}")
        self.assertGreaterEqual(
            emphasized, 10, "no corpus heading rendered as one; nothing here is checking"
        )


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
        # This comment used to say the fallback "cannot cross scripts". It
        # can: `tests/test_open_items.py` asks the same document in Arabic
        # with the Latin program name in the question and gets the English
        # passage back. What it cannot cross is a paraphrase — the fallback is
        # lexical, and between languages the only words that survive are
        # proper nouns and numbers. This question transliterates the name
        # instead of writing it, so nothing is shared and the honest outcome
        # is a refusal, in Arabic, in a right-to-left page.
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

    def test_no_pair_is_graded_as_dark_while_still_holding_a_light_colour(self):
        # The dark palette is the light one with the dark block's overrides
        # applied on top, so a token with no override silently keeps its light
        # value — and the contrast check below then grades a light colour and
        # reports it as dark. That check cannot notice: the light pair already
        # passes, which is why it is in the stylesheet. The pair above cannot
        # notice either, because one missing override out of twelve still
        # leaves the two palettes unequal.
        #
        # Add `--warning-bg` to `:root` and to PAIRS, forget the dark block,
        # and "every colour pair passes contrast in both presentations" is
        # true of eleven pairs and vacuous for the twelfth. So require what
        # this stylesheet already does: every colour a pair uses is re-themed.
        light, dark = palette("light"), palette("dark")
        used = {token for _, fg, bg, _ in PAIRS for token in (fg, bg)}
        unchanged = sorted(t for t in used if light[t] == dark.get(t))
        self.assertEqual(
            unchanged, [],
            "these tokens have no dark override, so the dark half of the "
            "contrast check is grading their light values",
        )

    def test_every_colour_the_stylesheet_declares_is_graded(self):
        # The population, from the stylesheet rather than from PAIRS. The
        # contrast check below iterates PAIRS, so a pair that fails can be
        # made to pass by deleting it: it leaves the loop, the colours stay in
        # the page, and the companion check above derives its universe from
        # PAIRS too and so loses sight of it as well. The stylesheet is the
        # thing that decides which colours the interface uses, so it is the
        # thing that decides what has to be graded.
        declared = set(palette("light"))
        graded = {token for _, fg, bg, _ in PAIRS for token in (fg, bg)}
        self.assertTrue(declared, "the stylesheet declares no colours")
        self.assertEqual(
            sorted(declared - graded), [],
            "these colours are in the stylesheet and in no graded pair",
        )

    def test_every_colour_pair_passes_contrast_in_both_presentations(self):
        # The same list of pairs an evidence bundle's interface snapshot
        # declares, so the auditor and this suite cannot disagree about which
        # colours the page uses. The check above is what stops that list from
        # shrinking away from the stylesheet.
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
        # The population first. Written in `px`, or dropped, and the loop
        # below iterates nothing and reports a pass — the stylesheet would
        # have stopped declaring a minimum and this would have stopped
        # noticing. tests/browser measures the rendered boxes; this is the
        # cheap half, and the cheap half has to know when it is empty.
        rules = re.findall(r"min-height:\s*([\d.]+)rem", CSS)
        self.assertGreaterEqual(len(rules), 2, "no control declares a minimum height")
        for rule in rules:
            self.assertGreaterEqual(float(rule) * 16, 24, "WCAG 2.2 target size minimum")


if __name__ == "__main__":
    unittest.main()
