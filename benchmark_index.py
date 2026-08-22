"""Benchmark: index build/read/query time and index file size at
larger-than-demo corpus scale.

Dev-only, standalone, stdlib-only — never imported by the `cairn` package
and never part of the runtime, the test suite's coverage floor, or the
audited evidence path. DESIGN.md says, of the index: "for corpora sized for
a laptop demo this is milliseconds; precomputed vectors are an optimization
the reference implementation does not need." This measures where that stops
being true, rather than asserting it forever — see the "larger real-corpus
support" item in the project's list of measured-not-promised claims.

Corpus generation is deterministic — no `random`, no timestamps, no wall
clock in the generated content — so a run against a given size has the same
*input* every time; only the timings, inherently, vary run to run.

Usage:
    python3 benchmark_index.py                        # default size ladder
    python3 benchmark_index.py --sizes 10 100 1000
    python3 benchmark_index.py --sizes 5000 --passages-per-doc 8 --queries 50

Nothing here is gated in CI. It is a measurement tool an operator or
contributor runs by hand when "is this still fast enough at my corpus's
real size" is the actual question.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.index import Index, build_and_write, read_index

DEFAULT_SIZES = (10, 100, 1000, 5000)

# A modest, fixed vocabulary so generated passages have realistic-ish
# term-frequency structure (some words common, some rare) without a
# dictionary or any randomness — words cycle deterministically by index.
_VOCAB = [
    "benefit", "program", "eligible", "household", "income", "monthly",
    "application", "deadline", "resident", "office", "assistance", "grant",
    "housing", "grocery", "transit", "utility", "credit", "renewal",
    "documentation", "appointment", "county", "service", "center", "amount",
]


def _passage_text(doc_index: int, passage_index: int) -> str:
    words = [_VOCAB[(doc_index * 7 + passage_index * 3 + i) % len(_VOCAB)] for i in range(30)]
    return " ".join(words) + "."


def generate_corpus(root: Path, doc_count: int, passages_per_doc: int) -> None:
    for i in range(doc_count):
        body = "\n\n".join(_passage_text(i, j) for j in range(passages_per_doc))
        (root / f"doc{i:06d}.md").write_text(
            f"---\nid: doc{i:06d}\ntitle: Program {i}\nlang: en\nsynthetic: true\n"
            f"---\n\n{body}\n",
            encoding="utf-8",
        )


def _queries(doc_count: int, n: int) -> list[str]:
    return [
        f"How much does the {_VOCAB[i % len(_VOCAB)]} program {i % doc_count} cover?"
        for i in range(n)
    ]


def benchmark_one(doc_count: int, passages_per_doc: int, query_count: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        corpus.mkdir()
        generate_corpus(corpus, doc_count, passages_per_doc)
        index_path = Path(tmp) / "index.json"

        t0 = time.perf_counter()
        report = build_and_write(corpus, index_path)
        build_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        index = read_index(index_path, corpus)
        read_s = time.perf_counter() - t0

        cfg = Config()
        query_times = [
            _time_one_query(index, cfg, q) for q in _queries(doc_count, query_count)
        ]

        return {
            "doc_count": doc_count,
            "passage_count": report.passage_count,
            "index_bytes": index_path.stat().st_size,
            "build_s": build_s,
            "read_s": read_s,
            "query_ms_median": statistics.median(query_times) * 1000 if query_times else 0.0,
            "query_ms_p95": (
                sorted(query_times)[max(0, int(len(query_times) * 0.95) - 1)] * 1000
                if query_times
                else 0.0
            ),
        }


def _time_one_query(index: Index, cfg: Config, question: str) -> float:
    t0 = time.perf_counter()
    ask(question, index, cfg)
    return time.perf_counter() - t0


def render(rows: list[dict]) -> str:
    header = (
        f"{'docs':>7} {'passages':>9} {'index KB':>9} {'build s':>8} "
        f"{'read s':>7} {'query ms (median / p95)':>24}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['doc_count']:>7} {r['passage_count']:>9} "
            f"{r['index_bytes'] / 1024:>9.1f} {r['build_s']:>8.3f} "
            f"{r['read_s']:>7.3f} "
            f"{r['query_ms_median']:>12.2f} / {r['query_ms_p95']:>7.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--passages-per-doc", type=int, default=4)
    parser.add_argument("--queries", type=int, default=20)
    args = parser.parse_args(argv)

    rows = [benchmark_one(size, args.passages_per_doc, args.queries) for size in args.sizes]
    print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
