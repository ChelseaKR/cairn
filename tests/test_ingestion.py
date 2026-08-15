"""R1: ingestion and indexing — reporting, idempotency, corpus validation."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from cairn.corpus import CorpusError, load_corpus, load_document
from cairn.index import build_and_write, read_index

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
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            build_and_write(DEMO, index_path)
            index = read_index(index_path)
            self.assertEqual(index.passage_count, len(index.passages))
            self.assertTrue(all(p.term_counts for p in index.passages))


if __name__ == "__main__":
    unittest.main()
