"""R1: ingestion and indexing — reporting, idempotency, corpus validation."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cairn.corpus import CorpusError, load_corpus, load_document
from cairn.index import LanguageStats, build_and_write, build_index, read_index, write_index

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"


class TestCorpusLoading(unittest.TestCase):
    def test_demo_corpus_loads_and_is_all_synthetic(self):
        docs = load_corpus(DEMO)
        self.assertGreaterEqual(len(docs), 4)
        self.assertTrue(all(d.synthetic for d in docs), "demo corpus must be labeled synthetic")
        langs = {d.lang for d in docs}
        self.assertLessEqual({"en", "es"}, langs, "demo corpus spans at least two languages")

    def test_passage_ids_are_stable_doc_ordinals(self):
        docs = load_corpus(DEMO)
        for doc in docs:
            for n, p in enumerate(doc.passages, start=1):
                self.assertEqual(p.passage_id, f"{doc.doc_id}#{n}")

    def test_heading_only_blocks_fold_into_following_passage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            path.write_text(
                "---\nid: t\ntitle: T\nlang: en\n---\nIntro paragraph.\n\n"
                "## A heading\n\nBody under the heading.\n",
                encoding="utf-8",
            )
            doc = load_document(path)
            self.assertEqual(len(doc.passages), 2)
            self.assertIn("## A heading", doc.passages[1].text)
            self.assertIn("Body under the heading.", doc.passages[1].text)

    def test_missing_front_matter_key_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            path.write_text("---\nid: t\ntitle: T\n---\nBody.\n", encoding="utf-8")
            with self.assertRaises(CorpusError):
                load_document(path)

    def write_doc(self, tmp, *, doc_id="t", lang="en"):
        path = Path(tmp) / "doc.md"
        path.write_text(
            f"---\nid: {doc_id}\ntitle: T\nlang: {lang}\n---\nBody paragraph.\n",
            encoding="utf-8",
        )
        return path

    def test_a_doc_id_that_cannot_be_cited_is_an_error(self):
        # Every answer from a document carries its id inside an inline
        # citation marker, and the interchange grammar for one is narrower
        # than "any string": it starts with a letter. `2024-winter-credit`
        # emits `[2024-winter-credit.2]`, which nothing recognises as a
        # citation — so grounded, correctly cited answers grade as uncited and
        # the audit reports a fabrication problem that does not exist. `#` is
        # refused for a second reason: it is the ordinal separator, so the
        # documents `a#b` and `a.b` both emit `[a.b.2]`.
        for doc_id in ("2024-winter-credit", "مخصص-البقالة", "grocery allowance", "a#b", "-x"):
            with self.subTest(doc_id=doc_id), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(CorpusError):
                    load_document(self.write_doc(tmp, doc_id=doc_id))
        for doc_id in ("grocery-allowance-en", "a.b", "T_9:x"):
            with self.subTest(doc_id=doc_id), tempfile.TemporaryDirectory() as tmp:
                loaded = load_document(self.write_doc(tmp, doc_id=doc_id))
                self.assertEqual(loaded.doc_id, doc_id)

    def test_a_language_subtag_does_not_make_a_new_language(self):
        # Retrieval scopes a search by comparing this string exactly, while
        # `direction_of` has always ignored subtags — so `lang: en-GB` was
        # English for layout and a language of its own for retrieval, and an
        # English question answered from that document came back labelled
        # cross-language: "the only source I have for this is written in
        # another language (en-GB)".
        for declared in ("en-GB", "EN", "en"):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as tmp:
                doc = load_document(self.write_doc(tmp, lang=declared))
                self.assertEqual(doc.lang, "en")
                self.assertTrue(all(p.lang == "en" for p in doc.passages))

    def test_reviewed_at_is_optional_and_passed_through_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            path.write_text(
                "---\nid: t\ntitle: T\nlang: en\nreviewed_at: 2026-01-15\n---\n"
                "Body paragraph.\n",
                encoding="utf-8",
            )
            self.assertEqual(load_document(path).reviewed_at, "2026-01-15")

    def test_reviewed_at_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = load_document(self.write_doc(tmp))
            self.assertIsNone(doc.reviewed_at)

    def test_an_unrecognized_front_matter_key_does_not_break_loading(self):
        # `reviewed_at` and `review` (import_corpus.py's marker) are two
        # concrete examples of a broader rule: front matter may carry keys
        # nothing here reads, and loading must not care.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            path.write_text(
                "---\nid: t\ntitle: T\nlang: en\nsome_future_key: whatever\n---\n"
                "Body paragraph.\n",
                encoding="utf-8",
            )
            doc = load_document(path)  # must not raise
            self.assertEqual(doc.doc_id, "t")


class TestIndexing(unittest.TestCase):
    def test_build_reports_counts_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            report = build_and_write(DEMO, index_path)
            self.assertGreater(report.doc_count, 0)
            self.assertGreater(report.passage_count, report.doc_count)
            self.assertEqual(report.synthetic_doc_count, report.doc_count)
            self.assertEqual(report.index_path, str(index_path))
            self.assertTrue(index_path.is_file())

    def test_an_index_that_does_not_add_up_is_refused(self):
        # Scoring is TF-IDF against per-language statistics, and `stats_for`
        # used to invent empty ones for a language it had never heard of.
        # Empty statistics give every term an IDF of exactly 1.0, so the
        # passage is scored on raw overlap with no stopword suppression at
        # all — "the" counts as much as the program's name — and it clears a
        # threshold calibrated against weighted scores. A hand-edited or
        # truncated index would have produced ungrounded answers labelled
        # grounded, silently. `build_index` cannot make one, which is why the
        # check belongs in the type that `read_index` also builds.
        from cairn.index import IndexError_

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            write_index(build_index(DEMO), path)
            payload = json.loads(path.read_text(encoding="utf-8"))

            broken = dict(payload, languages={"en": payload["languages"]["en"]})
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(IndexError_) as caught:
                read_index(path, DEMO)
            self.assertIn("ar", str(caught.exception))

            duplicated = dict(payload, passages=payload["passages"][:1] * 2)
            path.write_text(json.dumps(duplicated), encoding="utf-8")
            with self.assertRaises(IndexError_):
                read_index(path, DEMO)

            emptied = json.loads(json.dumps(payload))
            emptied["passages"][0]["text"] = "   "
            path.write_text(json.dumps(emptied), encoding="utf-8")
            with self.assertRaises(IndexError_):
                read_index(path, DEMO)

    def test_a_malformed_index_says_to_reindex_rather_than_traceback(self):
        from cairn.index import IndexError_

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            for content in ('{"format_version": 1, "passages"', '{"format_version": 1}'):
                with self.subTest(content=content[:24]):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(IndexError_):
                        read_index(path, DEMO)

    def test_reindexing_unchanged_corpus_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            build_and_write(DEMO, index_path)
            first = hashlib.sha256(index_path.read_bytes()).hexdigest()
            build_and_write(DEMO, index_path)
            second = hashlib.sha256(index_path.read_bytes()).hexdigest()
            self.assertEqual(
                first, second, "re-indexing an unchanged corpus must be idempotent"
            )

    def test_index_round_trips(self):
        # Against the index that was built, not against itself. The two
        # assertions this replaces were `len(x) == len(x)` — `passage_count`
        # is a property returning `len(self.passages)` — and `all(...)` over
        # the same list, which is True when the list is empty. A `read_index`
        # that dropped every passage passed both, in the only test that
        # exercises the round trip at all.
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            built = build_index(DEMO)
            write_index(built, index_path)
            index = read_index(index_path, DEMO)
            self.assertGreater(index.passage_count, 0)
            self.assertEqual(index.doc_count, built.doc_count)
            self.assertEqual(index.language_codes, built.language_codes)
            self.assertEqual(
                [p.passage_id for p in index.passages],
                [p.passage_id for p in built.passages],
            )
            for read_back, original in zip(index.passages, built.passages, strict=True):
                with self.subTest(passage=original.passage_id):
                    self.assertEqual(read_back.text, original.text)
                    self.assertEqual(read_back.lang, original.lang)
                    self.assertEqual(read_back.title, original.title)
                    self.assertEqual(read_back.term_counts, original.term_counts)
                    self.assertTrue(original.term_counts)


class TestDilutionExemption(unittest.TestCase):
    """`LanguageStats.dilution_exempt` tells apart the two ways
    `suppressed` can come back empty: a language with plenty of passages
    and nothing common enough to suppress (fine), and a language with so
    few passages that *every* term clears the ratio and the floor stands
    down entirely (the ``ck-022``-shaped trap `cairn lint` reports)."""

    def test_a_real_demo_language_is_not_exempt(self):
        index = build_index(DEMO)
        for lang, stats in index.languages.items():
            with self.subTest(lang=lang):
                self.assertFalse(stats.dilution_exempt)

    def test_a_single_passage_language_is_exempt(self):
        # Every term in a one-passage language has df == passage_count, so
        # every term clears `MAX_DF_RATIO * passage_count` and the floor
        # exempts the lot rather than suppress the passage to nothing.
        stats = LanguageStats(passage_count=1, doc_freq={"program": 1, "assist": 1})
        self.assertTrue(stats.dilution_exempt)
        self.assertEqual(stats.suppressed, frozenset())

    def test_a_language_with_no_terms_is_not_exempt(self):
        stats = LanguageStats(passage_count=0, doc_freq={})
        self.assertFalse(stats.dilution_exempt)

    def test_a_language_with_room_to_suppress_is_not_exempt(self):
        # A larger, more ordinary language: one term common enough to be
        # suppressed, one that is not. `suppressed` is non-empty here for
        # the ordinary reason, not the exemption.
        stats = LanguageStats(
            passage_count=10,
            doc_freq={"the": 8, "grant": 2},
        )
        self.assertEqual(stats.suppressed, frozenset({"the"}))
        self.assertFalse(stats.dilution_exempt)


if __name__ == "__main__":
    unittest.main()
