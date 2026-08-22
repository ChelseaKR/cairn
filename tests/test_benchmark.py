"""`benchmark_index.py` is dev-only tooling, not part of the runtime or the
audited evidence path, and not gated in CI — this is a smoke test that it
still runs and produces sane output, at a size trivial enough to stay fast."""

from __future__ import annotations

import contextlib
import io
import unittest


class TestBenchmarkRuns(unittest.TestCase):
    def test_a_tiny_run_produces_one_row_per_size(self):
        import benchmark_index

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = benchmark_index.main(
                ["--sizes", "3", "6", "--passages-per-doc", "2", "--queries", "2"]
            )
        self.assertEqual(code, 0)
        lines = out.getvalue().strip().splitlines()
        # Header, separator, one row per size.
        self.assertEqual(len(lines), 4)
        self.assertIn("docs", lines[0])
        self.assertIn("3", lines[2])
        self.assertIn("6", lines[3])

    def test_generated_corpora_are_deterministic(self):
        import tempfile
        from pathlib import Path

        import benchmark_index

        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            benchmark_index.generate_corpus(Path(tmp_a), doc_count=4, passages_per_doc=2)
            benchmark_index.generate_corpus(Path(tmp_b), doc_count=4, passages_per_doc=2)
            files_a = sorted(Path(tmp_a).glob("*.md"))
            files_b = sorted(Path(tmp_b).glob("*.md"))
            self.assertEqual([f.name for f in files_a], [f.name for f in files_b])
            for a, b in zip(files_a, files_b, strict=True):
                self.assertEqual(a.read_text(), b.read_text())

    def test_a_benchmark_run_produces_a_real_usable_index(self):
        # Not just "doesn't crash": the corpus it generates has to actually
        # parse and index the ordinary way.
        import tempfile
        from pathlib import Path

        import benchmark_index
        from cairn.index import build_index

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            benchmark_index.generate_corpus(corpus, doc_count=5, passages_per_doc=3)
            index = build_index(corpus)
            self.assertEqual(index.doc_count, 5)
            self.assertEqual(index.passage_count, 15)


if __name__ == "__main__":
    unittest.main()
