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
import re
import tomllib
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


class TestThePageNamesItsOwnAddress(PageHarness):
    """The head must point at this project's path, not at the shared origin.

    GitHub Pages serves this repository under a path on an origin five other
    projects also publish under, and `https://chelseakr.github.io/` is itself a
    404. Two mistakes are therefore available and both are silent: a canonical
    or `og:url` naming the bare origin, which tells a crawler that six
    unrelated projects are one page, and a root-relative reference, which
    resolves against the origin rather than `/cairn/` and so points at another
    project or at nothing at all.

    Neither shows up in a browser, because a browser reads the page it was
    already given. So the check is here rather than in a review pass.
    """

    def head(self) -> str:
        return self.source.split("</head>", 1)[0]

    def test_it_carries_a_self_referencing_canonical(self):
        self.assertIn(
            '<link rel="canonical" href="https://chelseakr.github.io/cairn/">',
            self.head(),
        )

    def test_every_absolute_url_it_claims_for_itself_keeps_the_project_path(self):
        # The canonical and og:url are the two tags whose whole job is to say
        # which page this is. Naming the origin is the failure mode; naming it
        # with the project path is the fix.
        claimed = re.findall(
            r'(?:<link rel="canonical" href|<meta property="og:url" content)="([^"]*)"',
            self.head(),
        )
        self.assertEqual(len(claimed), 2, f"expected canonical and og:url, got {claimed}")
        for url in claimed:
            self.assertEqual(url, "https://chelseakr.github.io/cairn/")

    def test_it_makes_no_root_relative_reference(self):
        # `href="/x"` and `src="/x"` resolve against chelseakr.github.io, not
        # against /cairn/. Protocol-relative `//host/x` is not this mistake and
        # is excluded rather than caught by accident.
        rooted = re.findall(r'(?:href|src|content)="(/(?!/)[^"]*)"', self.source)
        self.assertEqual(rooted, [], f"root-relative references escape /cairn/: {rooted}")

    def test_the_share_card_says_what_the_page_says(self):
        # A card that describes the page differently from the page is a second
        # claim nobody checked. Both come from one constant in the generator;
        # this holds the rendered result to that.
        head = self.head()
        for tag, value in (
            ("og:title", "Cairn — recorded evidence"),
            ("og:type", "website"),
            ("og:site_name", "Cairn"),
        ):
            self.assertIn(f'<meta property="{tag}" content="{value}">', head)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', head)

        description = re.search(r'<meta name="description" content="([^"]*)"', head)
        og_description = re.search(
            r'<meta property="og:description" content="([^"]*)"', head
        )
        self.assertIsNotNone(description)
        self.assertIsNotNone(og_description)
        self.assertEqual(description.group(1), og_description.group(1))

        title = re.search(r"<title>(.*?)</title>", head, re.S)
        og_title = re.search(r'<meta property="og:title" content="([^"]*)"', head)
        self.assertIsNotNone(title)
        self.assertIsNotNone(og_title)
        self.assertEqual(title.group(1), og_title.group(1))

    def test_the_share_card_names_an_image(self):
        # Without `og:image` a shared link renders as a gray box with no
        # picture, which is not a broken page and so never shows up in any
        # check that loads the page. The tag is the only place the absence is
        # visible from inside a checkout.
        head = self.head()
        for tag in ("og:title", "og:description", "og:image"):
            found = re.search(rf'<meta property="{tag}" content="([^"]*)"', head)
            self.assertIsNotNone(found, f"the head no longer carries {tag}")
            self.assertNotEqual(found.group(1).strip(), "", f"{tag} is empty")

        image = re.search(r'<meta property="og:image" content="([^"]*)"', head)
        twitter = re.search(r'<meta name="twitter:image" content="([^"]*)"', head)
        self.assertIsNotNone(twitter, "the head no longer carries twitter:image")
        self.assertEqual(
            image.group(1),
            twitter.group(1),
            "og:image and twitter:image name two different pictures",
        )
        # Same reasoning as the canonical: a preview fetcher has no page
        # context, so the image reference has to be absolute and has to keep
        # the project path or it points at a sibling project's site.
        self.assertEqual(image.group(1), "https://chelseakr.github.io/cairn/og-card.png")

    def test_the_image_the_card_names_is_committed_next_to_the_page(self):
        # The pages workflow uploads the `site` directory as it stands. A tag
        # naming a file that is not in it publishes a card that 404s, and the
        # 404 is on somebody else's screen, not in any log here.
        card = PAGE.parent / "og-card.png"
        self.assertTrue(card.is_file(), "site/og-card.png is missing")

        header = card.read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", "og-card.png is not a PNG")
        # Width and height are big-endian 32-bit fields of the IHDR chunk, at a
        # fixed offset. The tags in the head state 1200x630; a card of some
        # other size would make those two numbers a claim nothing checked.
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        self.assertEqual((width, height), (1200, 630))

        head = self.head()
        self.assertIn(f'<meta property="og:image:width" content="{width}">', head)
        self.assertIn(f'<meta property="og:image:height" content="{height}">', head)


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


class Head(HTMLParser):
    """The head, read as elements rather than as a string.

    Every value the structured data claims is also stated in an ordinary tag,
    so the check is an equality between the two. Reading them with a parser
    rather than a regular expression is not fastidiousness: the portfolio audit
    that asked for this markup scored a sibling project as carrying structured
    data because the string `application/ld+json` appeared on its page, and the
    single occurrence turned out to be the `accept` attribute of a file picker.
    A count of a string scores an upload widget as a schema.org node, and
    misses a real one written with unusual spacing. So this matches on the
    element and its `type`, and nothing else.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = ""
        self.canonical = ""
        self.meta: dict[str, str] = {}
        self.ld_blocks: list[str] = []
        self._in_title = False
        self._in_ld = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        at = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = at.get("lang", "")
        elif tag == "title":
            self._in_title = True
            self._buffer = []
        elif tag == "meta":
            key = at.get("name") or at.get("property")
            if key:
                self.meta[key] = at.get("content", "")
        elif tag == "link" and at.get("rel") == "canonical":
            self.canonical = at.get("href", "")
        elif tag == "script" and at.get("type", "").strip() == "application/ld+json":
            self._in_ld = True
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self.title = "".join(self._buffer)
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buffer))
            self._in_ld = False

    def handle_data(self, data):
        if self._in_title or self._in_ld:
            self._buffer.append(data)


class TestThePageSaysWhatItIsAbout(unittest.TestCase):
    """The machine-readable claim and the human-readable one are the same claim.

    The page states what it is twice: once in tags a person's browser renders,
    and once in a schema.org graph only a crawler reads. The second is the
    half nobody looks at, which makes it the half that rots — a title changed
    in the template and not in the node publishes two different answers to
    "what is this page", and the wrong one is the one the search result shows.

    So none of these tests assert a literal. Each one reads a value out of the
    graph and holds it against the tag, the file or the packaging metadata that
    the value is supposed to have come from. A node that stopped being derived
    would fail here even if it still said something plausible, which is the
    only failure worth catching: a node that is merely *wrong* is rare, and a
    node that is quietly stale is the normal outcome.

    Nothing here imports `site_build`, for the reason the module docstring
    gives about the other parse-and-compare class: asking the generator what
    the answer is cannot catch a generator that fabricates.
    """

    # Which published pages carry the graph, decided by name rather than by
    # whatever is under `site/` (owner decision 2026-09-18). The evidence page
    # is the page that says what this project is, so it is the one that says
    # it to a crawler. `privacy.html` says what the site collects about a
    # visitor, which is not a claim about the project, so it carries no graph.
    # Every page under `site/` has to be in exactly one of the two, so a page
    # added later is a decision somebody makes rather than one no test reads.
    GRAPH_PAGES = (PAGE,)
    WITHOUT_A_GRAPH = {
        PAGE.parent / "privacy.html": "says what the site collects, not what it is",
    }

    @classmethod
    def setUpClass(cls):
        cls.pages = sorted(PAGE.parent.rglob("*.html"))
        cls.graph_pages = [page for page in cls.pages if page in cls.GRAPH_PAGES]
        cls.parsed: dict[Path, Head] = {}
        for page in cls.pages:
            head = Head()
            head.feed(page.read_text(encoding="utf-8"))
            cls.parsed[page] = head
        cls.project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

    def graph(self, page: Path) -> dict[str, dict]:
        """Every node of a page's single JSON-LD block, keyed by `@id`."""
        blocks = self.parsed[page].ld_blocks
        self.assertEqual(
            len(blocks), 1, f"{page.name} carries {len(blocks)} ld+json blocks, expected 1"
        )
        payload = json.loads(blocks[0])
        self.assertEqual(payload.get("@context"), "https://schema.org")
        nodes = payload.get("@graph")
        self.assertIsInstance(nodes, list)
        return {node["@id"]: node for node in nodes}

    def test_there_is_a_page_to_examine(self):
        # The examinable set is every HTML file the pages workflow uploads. If
        # a future page lands in `site/` the loop below covers it without being
        # told; if the glob ever comes back empty, every other test in this
        # class would pass having read nothing, which is the failure this
        # repository's own audit notes call a gate that cannot fail.
        self.assertNotEqual(self.pages, [], "site/ holds no HTML to examine")

    def test_every_published_page_is_classified(self):
        # Every page either carries the graph or is named, with its reason, as
        # carrying none. A page in neither list is a page this class would
        # otherwise skip without saying so.
        self.assertEqual(
            set(self.pages),
            set(self.GRAPH_PAGES) | set(self.WITHOUT_A_GRAPH),
            "a page under site/ is neither described nor exempted by name",
        )
        self.assertFalse(set(self.GRAPH_PAGES) & set(self.WITHOUT_A_GRAPH))

    def test_a_page_without_a_graph_carries_none(self):
        # The exemption is a statement too. A graph that appeared on an
        # exempted page would be published and checked by nothing here.
        for page in self.WITHOUT_A_GRAPH:
            with self.subTest(page=page.name):
                self.assertIn(page, self.pages, f"{page.name} is not published")
                self.assertEqual(self.parsed[page].ld_blocks, [])

    def test_every_graph_page_carries_a_node(self):
        # The point of the gate: a page that should describe itself and does
        # not is the defect, and an absent node is invisible in a browser.
        self.assertNotEqual(self.graph_pages, [], "no page carries a graph")
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                self.assertNotEqual(
                    self.parsed[page].ld_blocks,
                    [],
                    f"{page.name} carries no application/ld+json block",
                )

    def test_every_block_is_valid_json_in_the_schema_org_vocabulary(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                self.graph(page)

    def test_the_graph_describes_the_page_the_site_and_the_software(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                types = {node["@type"] for node in self.graph(page).values()}
                self.assertEqual(
                    types,
                    {"WebSite", "WebPage", "ImageObject", "SoftwareApplication"},
                )

    def test_no_node_points_at_an_id_the_graph_does_not_define(self):
        # `"about": {"@id": ...}` naming a node that is not in the graph is a
        # reference to nothing, and consumers drop it silently rather than
        # complaining. It reads as a described page and is an empty one.
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                nodes = self.graph(page)
                for node in nodes.values():
                    for key, value in node.items():
                        if isinstance(value, dict) and "@id" in value:
                            self.assertIn(
                                value["@id"],
                                nodes,
                                f"{node['@type']}.{key} points at an undefined @id",
                            )

    def test_no_property_is_empty(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                for node in self.graph(page).values():
                    for key, value in node.items():
                        self.assertNotEqual(
                            value, "", f"{node['@type']}.{key} is an empty string"
                        )

    def test_the_page_node_repeats_the_pages_own_head(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                webpage = next(
                    n for n in self.graph(page).values() if n["@type"] == "WebPage"
                )
                self.assertEqual(webpage["name"], head.title)
                self.assertEqual(webpage["description"], head.meta["description"])
                self.assertEqual(webpage["url"], head.canonical)
                self.assertEqual(webpage["inLanguage"], head.lang)

    def test_the_site_node_repeats_the_pages_own_site_name(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                website = next(
                    n for n in self.graph(page).values() if n["@type"] == "WebSite"
                )
                self.assertEqual(website["name"], head.meta["og:site_name"])
                self.assertEqual(website["inLanguage"], head.lang)

    def test_the_image_node_repeats_the_card_the_head_names(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                image = next(
                    n for n in self.graph(page).values() if n["@type"] == "ImageObject"
                )
                self.assertEqual(image["url"], head.meta["og:image"])
                self.assertEqual(image["caption"], head.meta["og:image:alt"])
                self.assertEqual(str(image["width"]), head.meta["og:image:width"])
                self.assertEqual(str(image["height"]), head.meta["og:image:height"])

    def test_the_image_nodes_dimensions_are_the_committed_pngs_own(self):
        # The other half of the same claim. The tags and the node can agree
        # with each other and both be wrong about the file, which is what they
        # were before the generator started reading it.
        card = PAGE.parent / "og-card.png"
        header = card.read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        expected = (
            int.from_bytes(header[16:20], "big"),
            int.from_bytes(header[20:24], "big"),
        )
        image = next(
            n for n in self.graph(PAGE).values() if n["@type"] == "ImageObject"
        )
        self.assertEqual((image["width"], image["height"]), expected)

    def test_the_software_node_repeats_the_packaging_metadata(self):
        software = next(
            n for n in self.graph(PAGE).values() if n["@type"] == "SoftwareApplication"
        )
        self.assertEqual(software["alternateName"], self.project["name"])
        self.assertEqual(software["description"], self.project["description"])
        self.assertEqual(software["sameAs"], self.project["urls"]["Repository"])

    def test_the_page_and_the_packaging_agree_on_where_the_site_lives(self):
        # Two files now state this project's address: `pyproject.toml`, for the
        # PyPI page, and the generator, for the canonical. They were already
        # two copies before any of this; the node makes it three, so they get
        # held equal rather than left to drift.
        self.assertEqual(
            self.parsed[PAGE].canonical, self.project["urls"]["Homepage"]
        )

    def test_the_block_cannot_end_its_own_element(self):
        # The escaping in `structured_data` has no negative control available
        # from today's values: nothing in this page's title, description or
        # packaging metadata contains `<`, `>` or `&`, so deleting the escaping
        # chain changes no byte of the output and every other test here stays
        # green. That is a guard with nothing holding it, and the day a
        # description acquires an ampersand is not the day to find out.
        #
        # So this plants a value that needs escaping and asserts both halves:
        # the rendered block can no longer close its own element, and it still
        # decodes to exactly the text that went in.
        import site_build

        hostile = 'A sentence with </script><img src=x> and an & in it.'
        rendered = site_build.structured_data(1200, 630).replace(
            site_build.PAGE_DESCRIPTION, hostile
        )
        self.assertIn(hostile, rendered, "the substitution did not land")

        escaped = site_build.block_body(hostile)
        self.assertNotIn("</script", escaped)
        self.assertNotIn("<", escaped)
        self.assertNotIn(">", escaped)
        self.assertEqual(json.loads(escaped), hostile)

    def test_it_solicits_no_dataset_harvest(self):
        # Deliberate and permanent, not an oversight to be filled in later.
        #
        # A `Dataset` node, or DCAT beside it, is not a description — it is an
        # invitation. It exists so that dataset search engines and open-data
        # catalogs harvest the thing it names and list it as a dataset of
        # record, and a catalog listing is far easier to acquire than to
        # withdraw. This project publishes recorded answers about an invented
        # county, and whether any of this portfolio's derived corpora should
        # solicit that indexing is an open question with an owner's name on it.
        #
        # Saying "this page is about a piece of software" asks for none of it.
        # This test is here so that the difference stays a decision somebody
        # makes rather than a line somebody adds.
        forbidden = {"Dataset", "DataCatalog", "DataDownload", "DataFeed"}
        for page in self.pages:
            with self.subTest(page=page.name):
                raw = "".join(self.parsed[page].ld_blocks)
                for word in ("dcat:", "dct:", "void:", "distribution"):
                    self.assertNotIn(word, raw, f"{word} is harvest vocabulary")
                if page in self.graph_pages:
                    for node in self.graph(page).values():
                        self.assertNotIn(node["@type"], forbidden)


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
