"""`cairn/followup.py`: the write side (`FollowupStore`), the read side
(`load`/`render`), and the server/CLI wiring around both.

The recurring assertion, as with `tests/test_network.py` and
`tests/test_refusal_stats.py`: with `--followup-store` unset, nothing about
this feature is reachable at all — no route, no form, no change to a
refusal's response. And within the feature: the question is stored *only*
when the asker checked the box on that specific submission, never by
default.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from cairn.cli import main
from cairn.config import Config
from cairn.followup import FollowupStore, FollowupStoreError, load, render
from cairn.index import build_index
from cairn.server import build_handler

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"


class TestTheStoredRecordIsExactlyWhatIsPublished(unittest.TestCase):
    """Three fields, and nothing may join them without somebody deciding to.

    This is the one file Cairn writes that holds personal data a person typed
    about themselves, and three documents reason about exactly what is in it:
    `docs/followup.md` publishes the stored line verbatim, `docs/compliance.md`
    describes it for a records-retention review, and DESIGN.md argues the
    consent boundary around the one optional field. All three are prose, and
    prose about a data shape is checked by reading until something checks it.

    Reading is what it got, and reading missed one. `cairn/followup.py`'s own
    module docstring said the store held "a contact and a timestamp" from the
    day it was written until 2026-08-27, and no record has ever carried a
    timestamp. That was harmless in itself and it is the shape of the harmful
    version: a field added to `record()` for an ordinary operational reason -
    a timestamp for the retention schedule `docs/compliance.md` says the
    agency has to build itself, a client address for rate-limiting, a session
    id - would make all three documents quietly false about what an agency is
    holding on the people who contacted it.

    So the keys are enumerated here. A new one fails this test, which is the
    moment to write down why it is there and to move the three documents with
    it. That is deliberately more friction than adding a dict key, because
    this dict is somebody's phone number.
    """

    # The line `docs/followup.md` publishes, and the whole of it.
    STORED_FIELDS = {"lang", "contact", "question"}

    def record_one(self, **kwargs):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            FollowupStore(path).record(**kwargs)
            return json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    def test_a_record_carries_these_fields_and_no_others(self):
        for question in (None, "why was my application denied"):
            with self.subTest(question=question):
                entry = self.record_one(
                    lang="en", contact="a@example.gov", question=question
                )
                self.assertEqual(set(entry), self.STORED_FIELDS)

    def test_the_published_line_is_the_line_that_is_written(self):
        """Not "the fields match" but "the bytes match", against the example
        `docs/followup.md` shows an operator. A key added and documented in
        one place and not the other still fails here."""
        published = (
            Path(__file__).resolve().parent.parent / "docs" / "followup.md"
        ).read_text(encoding="utf-8")
        entry = self.record_one(
            lang="en", contact="someone@example.gov", question=None
        )
        self.assertIn(
            json.dumps(entry, ensure_ascii=False, sort_keys=True), published
        )

    def test_nothing_about_when_or_from_where_is_kept(self):
        """The two fields an append-only store of contact information most
        naturally grows, named so that growing one is a decision rather than
        an afternoon. A timestamp is what `cairn/followup.py`'s docstring
        claimed for months and what a retention period would need; an address
        is what the refusal counter refuses by construction."""
        entry = self.record_one(lang="en", contact="a@example.gov", question=None)
        for absent in ("timestamp", "time", "at", "received", "date",
                       "ip", "address", "client", "session", "id"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, entry)


class TestFollowupStore(unittest.TestCase):
    def test_a_missing_file_is_fine_to_start_from(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "does-not-exist-yet.jsonl"
            FollowupStore(path)  # constructing it writes nothing
            self.assertFalse(path.is_file())

    def test_recording_writes_one_json_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            store = FollowupStore(path)
            store.record(lang="en", contact="a@example.gov", question=None)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(
                entry, {"lang": "en", "contact": "a@example.gov", "question": None}
            )

    def test_the_question_is_stored_only_when_given(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            store = FollowupStore(path)
            store.record(lang="en", contact="a@example.gov", question="why not?")
            entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(entry["question"], "why not?")

    def test_multiple_requests_append_as_separate_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            store = FollowupStore(path)
            store.record(lang="en", contact="a@example.gov", question=None)
            store.record(lang="es", contact="b@example.gov", question="algo")
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)

    def test_only_a_directory_that_does_not_exist_yet_is_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nested" / "dir" / "store.jsonl"
            FollowupStore(path).record(lang="en", contact="a@example.gov", question=None)
            self.assertTrue(path.is_file())


class TestLoad(unittest.TestCase):
    def test_a_missing_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FollowupStoreError):
                load(Path(d) / "never-written.jsonl")

    def test_the_error_names_the_flag_that_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FollowupStoreError) as ctx:
                load(Path(d) / "never-written.jsonl")
            self.assertIn("--followup-store", str(ctx.exception))

    def test_requests_load_in_the_order_they_were_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            store = FollowupStore(path)
            store.record(lang="en", contact="first@example.gov", question=None)
            store.record(lang="es", contact="second@example.gov", question="algo")
            requests = load(path)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0].contact, "first@example.gov")
            self.assertEqual(requests[0].index, 1)
            self.assertEqual(requests[1].contact, "second@example.gov")
            self.assertEqual(requests[1].question, "algo")
            self.assertIsNone(requests[0].question)

    def test_blank_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            path.write_text(
                '{"lang": "en", "contact": "a@example.gov", "question": null}\n\n',
                encoding="utf-8",
            )
            requests = load(path)
            self.assertEqual(len(requests), 1)

    def test_a_malformed_line_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            path.write_text("not json at all {\n", encoding="utf-8")
            with self.assertRaises(FollowupStoreError):
                load(path)

    def test_a_line_missing_required_fields_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            path.write_text('{"lang": "en"}\n', encoding="utf-8")
            with self.assertRaises(FollowupStoreError):
                load(path)


class TestRender(unittest.TestCase):
    def test_zero_requests_says_so_plainly(self):
        self.assertEqual(render(()), "No follow-up requests recorded yet.")

    def test_every_request_appears_with_its_contact(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            store = FollowupStore(path)
            store.record(lang="en", contact="a@example.gov", question=None)
            store.record(lang="es", contact="555-0100", question="algo aqui")
            text = render(load(path))
            self.assertIn("2 follow-up request(s)", text)
            self.assertIn("a@example.gov", text)
            self.assertIn("555-0100", text)
            self.assertIn("algo aqui", text)
            self.assertIn("(not shared)", text)


class FollowupPage(HTMLParser):
    """Just enough parsing to find the follow-up form and its fields."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.details_classes = []
        self.forms = []
        self._current_form = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "details":
            self.details_classes.append(attrs.get("class", ""))
        if tag == "form":
            self._current_form = {"action": attrs.get("action"), "inputs": []}
            self.forms.append(self._current_form)
        if tag == "input" and self._current_form is not None:
            self._current_form["inputs"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self._current_form = None


class FollowupServerHarness(unittest.TestCase):
    followup_store = None

    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.index = build_index(DEMO)
        handler = build_handler(
            cls.cfg, cls.index, quiet=True, followup_store=cls.followup_store
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def ask_form(self, question, lang="en"):
        request = urllib.request.Request(
            self.base + "/ask",
            data=urllib.parse.urlencode({"question": question, "lang": lang}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")

    def ask_json(self, question, lang="en"):
        request = urllib.request.Request(
            self.base + "/ask",
            data=json.dumps({"question": question, "lang": lang}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_followup(self, fields, *, as_json=False):
        if as_json:
            request = urllib.request.Request(
                self.base + "/follow-up",
                data=json.dumps(fields).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        else:
            request = urllib.request.Request(
                self.base + "/follow-up",
                data=urllib.parse.urlencode(fields).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        return urllib.request.urlopen(request)


class TestNoStoreIsUnchanged(FollowupServerHarness):
    """The default: no followup_store at all, nothing new is reachable."""

    def test_no_followup_form_on_a_refusal(self):
        html = self.ask_form("purple elephants juggling unicycles")
        self.assertNotIn('class="followup"', html)

    def test_no_follow_up_available_hint_in_json(self):
        payload = self.ask_json("purple elephants juggling unicycles")
        self.assertEqual(payload.get("kind"), "refusal")
        self.assertNotIn("follow_up_available", payload)

    def test_follow_up_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_followup({"contact": "a@example.gov"})
        self.assertEqual(ctx.exception.code, 404)


class TestStoreEnabled(FollowupServerHarness):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store_path = Path(cls._tmp.name) / "store.jsonl"
        cls.followup_store = FollowupStore(cls.store_path)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def test_the_form_appears_on_a_refusal(self):
        html = self.ask_form("purple elephants juggling unicycles")
        page = FollowupPage(html)
        self.assertIn("followup", page.details_classes)
        forms = [f for f in page.forms if f["action"] == "/follow-up"]
        self.assertEqual(len(forms), 1)

    def test_the_form_carries_the_question_in_a_hidden_field(self):
        html = self.ask_form("purple elephants juggling unicycles")
        page = FollowupPage(html)
        followup_form = next(f for f in page.forms if f["action"] == "/follow-up")
        hidden = {
            i["name"]: i["value"] for i in followup_form["inputs"] if i["type"] == "hidden"
        }
        self.assertEqual(hidden.get("question"), "purple elephants juggling unicycles")

    def test_the_contact_field_is_required_text_not_email(self):
        html = self.ask_form("purple elephants juggling unicycles")
        page = FollowupPage(html)
        followup_form = next(f for f in page.forms if f["action"] == "/follow-up")
        contact = next(i for i in followup_form["inputs"] if i.get("name") == "contact")
        self.assertEqual(contact["type"], "text")
        self.assertIn("required", contact)

    def test_no_form_on_a_grounded_answer(self):
        html = self.ask_form("How much is the grocery allowance?")
        page = FollowupPage(html)
        self.assertNotIn("followup", page.details_classes)

    def test_json_refusal_carries_the_hint(self):
        payload = self.ask_json("purple elephants juggling unicycles")
        self.assertTrue(payload.get("follow_up_available"))

    def test_json_grounded_answer_carries_no_hint(self):
        payload = self.ask_json("How much is the grocery allowance?")
        self.assertNotIn("follow_up_available", payload)

    def test_submitting_without_the_checkbox_stores_no_question(self):
        with self.post_followup(
            {"contact": "a@example.gov", "lang": "en", "question": "the real question"}
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Thank you", response.read())
        requests = load(self.store_path)
        match = next(r for r in requests if r.contact == "a@example.gov")
        self.assertIsNone(match.question)

    def test_submitting_with_the_checkbox_stores_the_question(self):
        with self.post_followup(
            {
                "contact": "b@example.gov",
                "lang": "en",
                "question": "the real question",
                "include_question": "yes",
            }
        ):
            pass
        requests = load(self.store_path)
        match = next(r for r in requests if r.contact == "b@example.gov")
        self.assertEqual(match.question, "the real question")

    def test_missing_contact_is_a_400_and_nothing_is_stored(self):
        before = len(load(self.store_path)) if self.store_path.is_file() else 0
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_followup({"contact": "", "lang": "en", "question": "x"})
        self.assertEqual(ctx.exception.code, 400)
        after = len(load(self.store_path)) if self.store_path.is_file() else 0
        self.assertEqual(before, after)

    def test_json_submission_also_works(self):
        with self.post_followup(
            {
                "contact": "c@example.gov",
                "lang": "en",
                "question": "q",
                "include_question": True,
            },
            as_json=True,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
        self.assertEqual(body, {"received": True})
        requests = load(self.store_path)
        match = next(r for r in requests if r.contact == "c@example.gov")
        self.assertEqual(match.question, "q")

    def test_json_missing_contact_is_a_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_followup({"contact": "", "lang": "en"}, as_json=True)
        self.assertEqual(ctx.exception.code, 400)

    def test_a_malformed_json_body_is_a_400_not_a_traceback(self):
        request = urllib.request.Request(
            self.base + "/follow-up",
            data=b"not json at all {",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body, {"error": "malformed JSON body"})

    def test_a_json_body_that_parses_but_is_not_an_object_is_a_400(self):
        """#68's other route. The test above covers a body that does not
        parse; this covers one that parses to a list, a string, a number, a
        boolean or null, which `json.loads` accepts and `submitted.get`
        cannot take. It killed the handler thread and dropped the connection,
        so the asker of a refused question -- the person this whole route
        exists for -- got no confirmation and no error.

        Nothing is stored either way, and that is asserted rather than
        assumed: a bad request must not leave a partial record in a file that
        holds somebody's contact details.
        """
        before = len(load(self.store_path)) if self.store_path.is_file() else 0
        for body in (b"[1,2]", b'"hello"', b"5", b"null", b"true"):
            with self.subTest(body=body):
                request = urllib.request.Request(
                    self.base + "/follow-up",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request)
                self.assertEqual(ctx.exception.code, 400)
                self.assertEqual(
                    json.loads(ctx.exception.read().decode("utf-8")),
                    {"error": "malformed JSON body"},
                )
        after = len(load(self.store_path)) if self.store_path.is_file() else 0
        self.assertEqual(before, after, "a refused request stored something")


class TestCliFollowupsCommand(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_reports_a_written_store(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            FollowupStore(path).record(lang="en", contact="a@example.gov", question=None)
            code, out, _ = self.run_cli("followups", str(path))
            self.assertEqual(code, 0)
            self.assertIn("1 follow-up request(s)", out)

    def test_a_missing_file_is_a_clean_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "never-written.jsonl"
            code, out, err = self.run_cli("followups", str(path))
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("cairn: error:", err)
            self.assertIn("--followup-store", err)


if __name__ == "__main__":
    unittest.main()
