"""The published page says only what the committed evidence says.

`site/index.html` is served by GitHub Pages and is the first thing most people
will ever see of this project. It quotes recorded answers and prints audit
scores, which makes it the one surface where a drift between what the
repository tested and what the repository claims is visible to strangers and
invisible to everybody here — a demonstration page that has quietly stopped
matching its evidence is, for a project whose entire argument is about not
saying untested things, self-refuting.

Two checks, and the distinction between them is the point:

**Re-render and diff** (:class:`TestThePageIsNotStale`) catches a hand edit and
catches evidence that moved without the page being rebuilt. It cannot catch a
generator that fabricates, because it asks the generator what the answer is.

**Parse and compare** (:class:`TestThePageQuotesTheEvidence`) is the real one.
It reads the committed HTML with `html.parser`, pulls out the elements the page
marks as evidence, and holds the text it finds against `items.jsonl`,
`responses.jsonl`, `checksums.json` and `baseline.json`. Nothing in this class
imports `site_build`. If the generator started printing a friendlier answer
than Cairn gave, the first check would pass and this one would not.

Both run offline in the ordinary test suite, so the merge gate covers them and
the deploy is never the first place a drift is noticed. The deploy workflow
does not build the page; it uploads the committed file.
"""

from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "index.html"
BUNDLE = ROOT / "plumbline" / "bundle"
BASELINE = ROOT / "plumbline" / "baseline.json"


def jsonl(name: str) -> dict[str, dict]:
    return {
        json.loads(line)["id"]: json.loads(line)
        for line in (BUNDLE / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


class Evidence(HTMLParser):
    """Collects the text of every element carrying `data-evidence`.

    A deliberately small parser rather than a dependency: the core path of
    this repository is standard library only. It does not nest — no evidence
    element contains another — and it asserts that by refusing to open a
    second one while the first is still open, rather than silently keeping the
    inner text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, dict[str, str], list[str]]] = []
        self._open: tuple[str, str, dict[str, str], list[str]] | None = None
        self.rows: list[dict[str, str]] = []
        self.exchanges: list[str] = []  # article ids, in document order
        self._row: dict[str, str] | None = None
        self._cell: str | None = None

    def handle_starttag(self, tag, attrs):
        attributes = {k: (v or "") for k, v in attrs}
        if "data-exchange" in attributes:
            self.exchanges.append(attributes["data-exchange"])
        if "data-evidence" in attributes:
            if self._open is not None:
                raise AssertionError(
                    f"evidence element <{tag}> opened inside "
                    f"<{self._open[0]} data-evidence={self._open[2]['data-evidence']}>"
                )
            if attributes["data-evidence"] == "suite":
                self._row = dict(attributes)
                return
            self._open = (tag, attributes["data-evidence"], attributes, [])
            return
        if self._row is not None and tag in ("td", "th"):
            self._cell = attributes.get("data-field", "name")

    def handle_data(self, data):
        if self._open is not None:
            self._open[3].append(data)
        elif self._cell is not None and self._row is not None:
            self._row[self._cell] = self._row.get(self._cell, "") + data

    def handle_endtag(self, tag):
        if self._open is not None and tag == self._open[0]:
            _, kind, attributes, chunks = self._open
            self.found.append((kind, attributes, chunks))
            self._open = None
        elif self._cell is not None and tag in ("td", "th"):
            self._cell = None
        elif self._row is not None and tag == "tr":
            self.rows.append(self._row)
            self._row = None

    def text(self, kind: str) -> dict[str, str]:
        """`{item id: text}` for every element of one evidence kind."""
        out = {}
        for found_kind, attributes, chunks in self.found:
            if found_kind == kind:
                out[attributes.get("data-item", attributes.get("data-evidence"))] = (
                    "".join(chunks)
                )
        return out


class PageHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PAGE.is_file():
            raise AssertionError(f"{PAGE} is not committed; run `python3 site_build.py`")
        cls.source = PAGE.read_text(encoding="utf-8")
        cls.evidence = Evidence()
        cls.evidence.feed(cls.source)
        cls.items = jsonl("items.jsonl")
        cls.responses = {k: v["response"] for k, v in jsonl("responses.jsonl").items()}
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))


class TestThePageQuotesTheEvidence(PageHarness):
    def test_the_parser_found_something_to_check(self):
        # Every assertion below iterates over what the parser found. An empty
        # parse — a renamed attribute, a markup change the parser cannot
        # follow — would satisfy all of them, which is the shape of vacuous
        # check this repository keeps finding in its own suite.
        prompts = self.evidence.text("prompt")
        responses = self.evidence.text("response")
        self.assertGreaterEqual(len(prompts), 3, prompts)
        self.assertEqual(set(prompts), set(responses))
        self.assertGreaterEqual(len(self.evidence.rows), 14, self.evidence.rows)

    def test_every_question_shown_is_the_question_that_was_asked(self):
        for item_id, shown in self.evidence.text("prompt").items():
            with self.subTest(item=item_id):
                self.assertIn(item_id, self.items, "the page shows an item not in the bundle")
                self.assertEqual(shown, self.items[item_id]["prompt"])

    def test_every_answer_shown_is_the_answer_that_was_recorded(self):
        # Character for character, bidi isolates included. The cross-language
        # notice carries U+2067/U+2069 around the Latin language name, and a
        # page that dropped them would be showing a string Cairn did not emit.
        for item_id, shown in self.evidence.text("response").items():
            with self.subTest(item=item_id):
                self.assertEqual(shown, self.responses[item_id])

    def test_the_page_leads_with_a_refusal(self):
        # Ordered by position in the document, not by anything the page says
        # about itself.
        order = self.evidence.exchanges
        self.assertGreaterEqual(len(order), 3, order)
        self.assertEqual(self.items[order[0]]["behavior"], "refuse")
        self.assertEqual(self.items[order[0]]["sources"], [])

    def test_a_refusal_is_shown_as_citing_nothing(self):
        self.assertTrue(self.evidence.exchanges)
        for item_id in self.evidence.exchanges:
            item = self.items[item_id]
            with self.subTest(item=item_id):
                block = self.block_for(item_id)
                if item["behavior"] == "refuse":
                    self.assertIn("No sources", block)
                    self.assertNotIn("Cited:", block)
                else:
                    self.assertIn("Cited:", block)
                    self.assertTrue(item["sources"])
                    for source in item["sources"]:
                        self.assertIn(source, block)

    def block_for(self, item_id: str) -> str:
        start = self.source.index(f'data-exchange="{item_id}"')
        return self.source[start : self.source.index("</article>", start)]

    def test_the_cross_language_answer_is_marked_up_as_two_languages(self):
        # The Arabic notice and the English passage arrive in one string, and
        # the page states the language of the whole exchange as Arabic. That
        # is what the recorded response is; what must not happen is the page
        # claiming the *source* was Arabic.
        block = self.block_for("ck-027")
        self.assertIn('lang="ar"', block)
        self.assertIn('dir="rtl"', block)
        self.assertTrue(
            self.items["ck-027"]["sources"], "the item stopped carrying sources"
        )
        for source in self.items["ck-027"]["sources"]:
            self.assertIn(source, block)
            self.assertTrue(source.startswith("transit-pass-en"), source)

    def test_every_score_shown_is_the_committed_baseline(self):
        committed = {s["suite"]: s for s in self.baseline["suites"]}
        shown = {row["data-suite"]: row for row in self.evidence.rows}
        self.assertEqual(set(shown), set(committed), "the table is not the baseline")
        for suite, row in shown.items():
            with self.subTest(suite=suite):
                entry = committed[suite]
                self.assertEqual(row["score"], f"{entry['score']:.4f}")
                self.assertEqual(row["floor"], f"{entry['floor']:.2f}")
                self.assertEqual(row["n"], str(entry["n"]))
                self.assertEqual(row["verdict"], entry["verdict"])

    def test_the_dataset_id_shown_is_the_bundle_s_own_hash(self):
        checksums = json.loads((BUNDLE / "checksums.json").read_text(encoding="utf-8"))
        shown = self.evidence.text("dataset-id")["dataset-id"]
        self.assertTrue(checksums["bundle_sha256"].startswith(shown), shown)
        self.assertGreaterEqual(len(shown), 12)

    def test_the_multilingual_sentence_is_the_baseline_s_arithmetic(self):
        entry = next(s for s in self.baseline["suites"] if s["suite"] == "multilingual")
        passed = round(entry["score"] * entry["n"])
        self.assertEqual(passed, entry["n"] - 1, "the open item says exactly one fails")
        self.assertIn(f"{passed} of {entry['n']} items pass it", self.source)

    def test_the_page_says_the_corpus_is_invented(self):
        # The refusals quote a fictional phone number and the answers quote
        # invented policy amounts. A visitor who does not know that is being
        # shown a public-benefits page that looks real.
        self.assertIn("synthetic", self.source)
        self.assertIn("fictional", self.source)


class TestThePageIsNotStale(PageHarness):
    def test_it_is_what_the_committed_evidence_renders_to(self):
        # This one *does* ask the generator, which is why it is not the check
        # above. It catches the file being hand-edited and the evidence moving
        # without a rebuild; it cannot catch the generator inventing, and does
        # not claim to.
        import site_build

        self.assertEqual(self.source, site_build.render())

    def test_the_check_mode_agrees(self):
        import site_build

        self.assertEqual(site_build.main(["--check"]), 0)


class TestTheDeployedPageIsTheCommittedPage(unittest.TestCase):
    """The workflow must upload the file, not rebuild it.

    A deploy that regenerates is a deploy that can serve something no reviewer
    saw. The check that the page matches the evidence runs in `core`, which is
    a required context; the deploy runs `--check` again and refuses to publish
    on a mismatch, so neither half depends on the other having been run.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"

    def setUp(self):
        self.source = self.WORKFLOW.read_text(encoding="utf-8")

    def test_the_deploy_verifies_before_it_publishes(self):
        self.assertIn("site_build.py --check", self.source)
        verify = self.source.index("site_build.py --check")
        upload = self.source.index("upload-pages-artifact")
        self.assertLess(verify, upload, "it publishes before it checks")

    def test_the_deploy_does_not_regenerate_the_page(self):
        for line in self.source.splitlines():
            stripped = line.split("#", 1)[0]
            if "site_build.py" in stripped:
                self.assertIn("--check", stripped, f"this step rebuilds the page: {line}")

    def test_every_action_is_pinned_to_a_commit(self):
        import re

        uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", self.source, flags=re.MULTILINE)
        self.assertGreaterEqual(len(uses), 3, uses)
        for reference in uses:
            with self.subTest(action=reference):
                self.assertRegex(
                    reference, r"@[0-9a-f]{40}$",
                    "pin the action to a commit; a tag can move under you",
                )

    def test_it_asks_for_no_more_than_it_needs(self):
        self.assertIn("contents: read", self.source)
        self.assertIn("pages: write", self.source)
        self.assertIn("id-token: write", self.source)
        self.assertNotIn("contents: write", self.source)
        self.assertNotIn("permissions: write-all", self.source)


if __name__ == "__main__":
    unittest.main()
