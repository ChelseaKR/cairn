"""Every number this repository publishes about its own audit, derived.

`tests/test_docs.py` already holds the executed console blocks byte for byte,
and holds the dataset id, the test count and the browser-check count against
what produces them. It does not reach the gate and guard transcripts, which
are fenced as ``text`` because they need the network the first time, or the
`Measured` values in `plumbline/target.toml`, which `audit_guard.py` prints
beside every verdict. Those were maintained by hand, and by 2026-08-29 six of
them had stopped being true:

- `README.md` and `docs/demo.md` both printed
  ``Bundle sha256: b7a28017...`` three lines above ``dataset 124f7e4a41ba``.
  Those are the same hash written two ways, and they disagreed: the committed
  bundle hashes to ``124f7e4a41ba...``. The dataset id was checked; the
  full hash on the line above it was not.
- `README.md` printed ``multilingual score 0.9655 ... n=29`` against a
  committed baseline of 0.9667 over 30.
- both documents printed ``3 unverifiable`` for `passage_attribution` next to
  a guard line saying ``18 of 22 eligible (no_distractor 4)``.
- `docs/demo.md` printed ``scored 17 of 20 eligible (no_distractor 3)`` and
  ``declared gaps: none — every implemented suite is enabled``, while
  `plumbline/target.toml` declares `conversational_integrity` disabled with a
  gap and `README.md` printed the gap.
- `README.md` and `docs/demo.md` said `passage_attribution` "scores 0.9412
  over 17 items" against a committed 0.9444 over 18.
- `plumbline/target.toml` recorded ``Measured 0.3982`` for `accuracy` (0.4132),
  ``Measured 1.0000`` for `groundedness` and `citation_accuracy` (0.9740 each),
  and ``over 4 probes`` for `adversarial` (6). That file says in its own
  header that "Measurements are from the committed baseline", and
  `audit_guard.py` prints every non-default floor's reason beside the verdict,
  so those numbers are shown to a reader as the justification for a floor.

Nothing was red, because nothing read them. The committed baseline was right
the whole time; what had rotted was every hand-typed copy of it.

Two things are deliberately NOT checked here, and are elided in the documents
instead, following this repository's own precedent for the run id
(`test_no_document_publishes_a_run_id_nothing_can_check`): the confidence
interval and the minimum detectable effect. Both are the pinned harness's
arithmetic, this suite runs with the harness unreachable, and reimplementing
them here would be a second definition that could drift from the first. A
number with no check under it is elided rather than published.
"""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "plumbline" / "baseline.json"
CHECKSUMS = ROOT / "plumbline" / "bundle" / "checksums.json"
ITEMS = ROOT / "plumbline" / "bundle" / "items.jsonl"
DATASET_CARD = ROOT / "plumbline" / "bundle" / "DATASET.md"
TARGET = ROOT / "plumbline" / "target.toml"
CARD = "plumbline/bundle/DATASET.md"

# The two documents that publish a gate transcript. DESIGN.md is out of scope
# for the same reason tests/test_docs.py excludes it: its transcripts are
# captured from deliberately broken trees, so holding them to the committed
# run would require them to be the thing they exist to differ from.
DOCUMENTS = ("README.md", "docs/demo.md")

SUITE_LINE = re.compile(
    r"^ *(?P<suite>[a-z_]+) +score +(?P<score>[0-9]+\.[0-9]+)"
    r" +floor +(?P<floor>[0-9]+\.[0-9]+)"
    r" +(?P<verdict>PASS|FAIL)"
    r" +n=(?P<n>[0-9]+)"
    r"(?P<rest>.*)$",
    re.MULTILINE,
)
UNVERIFIABLE = re.compile(r"(?P<count>[0-9]+) unverifiable")
COVERAGE_LINE = re.compile(
    r"(?P<suite>[a-z_]+): scored (?P<scored>[0-9]+) of (?P<eligible>[0-9]+) "
    r"eligible \(no_distractor (?P<excluded>[0-9]+)\)"
)
BUNDLE_SHA = re.compile(r"Bundle sha256: ([0-9a-f]{6,})")
SUITE_COUNT = re.compile(r"all ([0-9]+) suites passed")
RECORDED = re.compile(
    r"Recorded (?P<items>[0-9]+) items \((?P<answers>[0-9]+) answers, "
    r"(?P<refusals>[0-9]+) refusals\) in (?P<langs>[0-9]+) languages "
    r"\[(?P<list>[^\]]*)\]"
)


def baseline() -> dict[str, dict]:
    return {s["suite"]: s
            for s in json.loads(BASELINE.read_text(encoding="utf-8"))["suites"]}


def items() -> list[dict]:
    return [json.loads(line)
            for line in ITEMS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def document(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class PublishedFigures(unittest.TestCase):
    def assertSays(self, name: str, sentence: str, text: str | None = None):
        """Fail with the sentence, never with the document.

        `assertIn` prints the haystack, and the haystack here is a README.
        A drift report a reader has to scroll past a whole document to find
        is a report nobody reads.
        """
        haystack = re.sub(r"\s+", " ", document(name) if text is None else text)
        if sentence not in haystack:
            self.fail(
                f"{name} does not say: {sentence}\n"
                f"That figure comes from a committed artifact. The sentence "
                f"does not, so it is the sentence that is stale.")


class TestTheTranscriptsAreTheCommittedRun(PublishedFigures):
    """A published score line is the committed baseline's, or it is fiction."""

    def setUp(self):
        self.baseline = baseline()

    def test_every_published_suite_line_matches_the_committed_baseline(self):
        seen = 0
        for name in DOCUMENTS:
            for line in SUITE_LINE.finditer(document(name)):
                suite = line.group("suite")
                if suite not in self.baseline:
                    continue  # a suite this target does not score
                seen += 1
                committed = self.baseline[suite]
                with self.subTest(document=name, suite=suite):
                    self.assertEqual(
                        line.group("score"), f"{committed['score']:.4f}",
                        f"{name} publishes a {suite} score the committed "
                        f"baseline does not hold")
                    self.assertEqual(line.group("floor"),
                                     f"{committed['floor']:.2f}")
                    self.assertEqual(line.group("verdict"),
                                     committed["verdict"])
                    self.assertEqual(int(line.group("n")), committed["n"])
        self.assertGreaterEqual(
            seen, 3, "no document publishes a suite score line any more")

    def test_no_published_suite_line_quotes_a_ci_or_mde(self):
        # Both are the pinned harness's arithmetic and this suite runs with
        # the harness unreachable, so a literal here is a number with no check
        # under it — the shape the run id was elided for.
        for name in DOCUMENTS:
            for line in SUITE_LINE.finditer(document(name)):
                with self.subTest(document=name, suite=line.group("suite")):
                    for figure in ("ci", "mde"):
                        found = re.search(rf"\b{figure} ([0-9][^ ]*)",
                                          line.group("rest"))
                        self.assertIsNone(
                            found,
                            f"elide the {figure} (`{figure} ...`): nothing "
                            f"offline can recompute it")

    def test_the_published_suite_count_is_the_number_of_suites_scored(self):
        seen = 0
        for name in DOCUMENTS:
            for count in SUITE_COUNT.findall(document(name)):
                seen += 1
                with self.subTest(document=name):
                    self.assertEqual(int(count), len(self.baseline))
        self.assertGreaterEqual(seen, 2)
        self.assertTrue(all(s["verdict"] == "PASS"
                            for s in self.baseline.values()),
                        "a document says every suite passed and one did not")

    def test_every_published_bundle_hash_is_the_committed_bundle_s(self):
        committed = json.loads(
            CHECKSUMS.read_text(encoding="utf-8"))["bundle_sha256"]
        seen = 0
        for name in DOCUMENTS:
            for shown in BUNDLE_SHA.findall(document(name)):
                seen += 1
                with self.subTest(document=name, shown=shown[:12]):
                    self.assertTrue(
                        committed.startswith(shown),
                        f"{name} publishes bundle sha256 {shown[:12]}..., but "
                        f"the committed bundle hashes to {committed[:12]}...")
        self.assertGreaterEqual(seen, 2, "no document shows a bundle hash")

    def test_every_published_coverage_line_adds_up_and_names_the_scored_n(self):
        # `scored 18 of 22 eligible (no_distractor 4)` carries three numbers
        # that constrain each other and one the baseline pins. The two
        # documents disagreed with each other and with the baseline on all
        # three, which is the arithmetic nobody was doing.
        seen = 0
        for name in DOCUMENTS:
            text = document(name)
            for found in COVERAGE_LINE.finditer(text):
                seen += 1
                suite = found.group("suite")
                scored = int(found.group("scored"))
                eligible = int(found.group("eligible"))
                excluded = int(found.group("excluded"))
                with self.subTest(document=name, suite=suite):
                    self.assertEqual(
                        eligible - scored, excluded,
                        f"{name}: {suite} says {scored} of {eligible} with "
                        f"{excluded} excluded, and those do not add up")
                    self.assertIn(suite, self.baseline)
                    self.assertEqual(
                        scored, self.baseline[suite]["n"],
                        f"{name}: {suite} scored {scored} items, but the "
                        f"committed baseline records n="
                        f"{self.baseline[suite]['n']}")
                    for line in SUITE_LINE.finditer(text):
                        if line.group("suite") != suite:
                            continue
                        unverifiable = UNVERIFIABLE.search(line.group("rest"))
                        if unverifiable is None:
                            continue
                        self.assertEqual(
                            int(unverifiable.group("count")), excluded,
                            f"{name}: the {suite} line says "
                            f"{unverifiable.group('count')} unverifiable and "
                            f"the coverage line says {excluded}")
        self.assertGreaterEqual(seen, 2)

    def test_the_prose_about_passage_attribution_is_the_committed_score(self):
        committed = self.baseline["passage_attribution"]
        self.assertSays(
            "README.md", f"{committed['score']:.4f} over {committed['n']} items")
        self.assertSays(
            "docs/demo.md",
            f"{committed['score']:.4f} is one item failing it")

    def test_a_document_that_says_gaps_exist_agrees_with_the_declaration(self):
        target = tomllib.loads(TARGET.read_text(encoding="utf-8"))
        declared = sorted(name for name, cfg in target["suites"].items()
                          if not cfg.get("enabled", True))
        self.assertTrue(declared, "no suite is disabled; re-scope this check")
        for name in DOCUMENTS:
            text = document(name)
            with self.subTest(document=name):
                found = re.search(
                    r"declared gaps(?: \((?P<count>[0-9]+) suites? not scored "
                    r"at all\))?: ?(?P<none>none)?", text)
                self.assertIsNotNone(
                    found, f"{name} no longer shows the guard's gap line")
                self.assertIsNone(
                    found.group("none"),
                    f"{name} says no gap is declared; "
                    f"plumbline/target.toml declares {declared}")
                self.assertEqual(int(found.group("count")), len(declared))
                for suite in declared:
                    self.assertIn(suite, text)


class TestTheRecordingLineIsTheRecording(unittest.TestCase):
    def test_every_published_record_summary_is_the_committed_bundle(self):
        recorded = items()
        answers = sum(1 for i in recorded if i["behavior"] == "answer")
        refusals = sum(1 for i in recorded if i["behavior"] == "refuse")
        langs = sorted({i["lang"] for i in recorded})
        seen = 0
        for name in DOCUMENTS:
            for found in RECORDED.finditer(document(name)):
                seen += 1
                with self.subTest(document=name):
                    self.assertEqual(int(found.group("items")), len(recorded))
                    self.assertEqual(int(found.group("answers")), answers)
                    self.assertEqual(int(found.group("refusals")), refusals)
                    self.assertEqual(int(found.group("langs")), len(langs))
                    self.assertEqual(
                        [part.strip()
                         for part in found.group("list").split(",")], langs)
        self.assertGreaterEqual(seen, 2)


class TestTheDatasetCardCountsWhatIsInTheBundle(PublishedFigures):
    """`DATASET.md` ships inside the hashed bundle and counts it by hand.

    Its sha256 is in `checksums.json`, so it cannot be edited without
    resealing — but `cairn record` does not write it, so the bundle can grow,
    reseal, and leave the card counting a bundle that no longer exists.
    """

    def setUp(self):
        self.items = items()
        self.card = DATASET_CARD.read_text(encoding="utf-8")

    def test_it_counts_the_items_and_the_languages(self):
        langs: dict[str, int] = {}
        for item in self.items:
            langs[item["lang"]] = langs.get(item["lang"], 0) + 1
        breakdown = ", ".join(f"{n} {lang}"
                              for lang, n in sorted(langs.items()))
        self.assertSays(CARD, f"{len(self.items)} items ({breakdown}).",
                        self.card)

    def test_it_counts_the_behaviors_and_the_adversarial_probes(self):
        answers = sum(1 for i in self.items if i["behavior"] == "answer")
        refusals = sum(1 for i in self.items if i["behavior"] == "refuse")
        adversarial = sum(1 for i in self.items if i.get("adversarial"))
        self.assertSays(
            CARD,
            f"{answers} expected answers, {refusals} expected refusals, "
            f"{adversarial} of", self.card)

    def test_it_counts_the_unreviewed_translations(self):
        non_english = [i for i in self.items if i["lang"] != "en"]
        unreviewed = [i for i in non_english
                      if (i.get("translation") or {}).get("review")
                      == "unreviewed"]
        authored = len(non_english) - len(unreviewed)
        self.assertSays(CARD, f"{len(non_english)} items are not in English.",
                        self.card)
        self.assertSays(CARD, f"{len(unreviewed)} of them are", self.card)
        self.assertSays(CARD, f"the remaining {authored} were", self.card)


class TestThePilotCandidateCountsAreCounted(PublishedFigures):
    """`docs/pilot-ca.md` counts a file it does not read.

    `corpus/pilot-ca/candidates.toml` is `collect_queries.py`'s output, and
    the page publishes its size and its split by source. Regenerating it is
    not possible offline — the collector draws from MS MARCO and Stack
    Exchange dumps that are deliberately not committed — so the file itself
    cannot be byte-compared here. Its counts can be, and are: they are the
    part of the claim that goes stale when somebody adds or drops candidates.
    """

    def test_the_page_counts_the_candidates_that_are_committed(self):
        candidates = tomllib.loads(
            (ROOT / "corpus" / "pilot-ca" / "candidates.toml")
            .read_text(encoding="utf-8"))["item"]
        by_source: dict[str, int] = {}
        for item in candidates:
            by_source[item["source"]] = by_source.get(item["source"], 0) + 1
        self.assertSays(
            "docs/pilot-ca.md",
            f"holds {len(candidates)} candidates "
            f"({by_source['search-query']} search queries, "
            f"{by_source['stackexchange']} Stack Exchange)")


class TestTheFloorReasonsQuoteTheCommittedBaseline(PublishedFigures):
    """`plumbline/target.toml` says its measurements come from the baseline.

    It said so and nothing checked it, so four of them stopped being true
    while `audit_guard.py` went on printing them beside the verdict as the
    justification for a floor. A stale measurement in that position is worse
    than none: it is the argument for the bar, and a reader has no way to see
    that the bar was set against a number the system no longer produces.
    """

    MEASURED = re.compile(
        r"Measured (?P<score>[0-9]+\.[0-9]{4})"
        r"(?: over (?P<n>[0-9]+) (?:probes|scored items|items))?")

    def test_every_measured_value_in_a_floor_reason_is_the_committed_score(self):
        committed = baseline()
        target = tomllib.loads(TARGET.read_text(encoding="utf-8"))
        seen = 0
        for suite, cfg in sorted(target["suites"].items()):
            reason = cfg.get("floor_reason")
            if not reason:
                continue
            self.assertIn(suite, committed, f"{suite} is not in the baseline")
            for found in self.MEASURED.finditer(reason):
                seen += 1
                with self.subTest(suite=suite):
                    self.assertEqual(
                        found.group("score"),
                        f"{committed[suite]['score']:.4f}",
                        f"[suites.{suite}] floor_reason reports "
                        f"{found.group('score')}; the committed baseline "
                        f"scores {committed[suite]['score']:.4f}")
                    if found.group("n"):
                        self.assertEqual(int(found.group("n")),
                                         committed[suite]["n"])
        self.assertGreaterEqual(
            seen, 4, "no floor_reason reports a measurement any more")

    def test_every_suite_with_a_nondefault_floor_reason_is_one_that_is_scored(self):
        # A reason attached to a suite the baseline does not score is a reason
        # nothing above can check.
        committed = baseline()
        target = tomllib.loads(TARGET.read_text(encoding="utf-8"))
        for suite, cfg in sorted(target["suites"].items()):
            if cfg.get("floor_reason"):
                self.assertIn(suite, committed)


if __name__ == "__main__":
    unittest.main()
