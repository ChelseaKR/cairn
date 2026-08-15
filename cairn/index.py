"""On-disk index: build, write, read.

The index is one JSON file holding passage records, per-passage term counts,
document frequencies, and totals. Serialization uses sorted keys, a fixed
key order, and no timestamps, so re-indexing an unchanged corpus produces a
byte-identical file — idempotency (spec R1) is checkable with a file hash.

Scores are computed at query time from the stored term counts; for corpora
sized for a laptop demo there is nothing to precompute.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cairn.corpus import load_corpus

INDEX_FORMAT_VERSION = 1

_WORD_RE = re.compile(r"\w+", re.UNICODE)


class IndexError_(ValueError):
    """The index file is missing, unreadable, or from another format version."""


def tokenize(text: str) -> list[str]:
    """Unicode word tokens, casefolded. Language-agnostic by design: the same
    tokenizer serves Latin-script and RTL-script corpora (DESIGN.md)."""
    return [m.group(0).casefold() for m in _WORD_RE.finditer(text)]


@dataclass(frozen=True)
class IndexedPassage:
    passage_id: str
    doc_id: str
    title: str
    lang: str
    text: str
    term_counts: dict[str, int]


@dataclass(frozen=True)
class Index:
    passages: tuple[IndexedPassage, ...]
    doc_freq: dict[str, int]
    doc_count: int
    synthetic_doc_count: int

    @property
    def passage_count(self) -> int:
        return len(self.passages)


@dataclass(frozen=True)
class BuildReport:
    doc_count: int
    passage_count: int
    synthetic_doc_count: int
    index_path: str


def build_index(corpus_dir: str | Path) -> Index:
    docs = load_corpus(corpus_dir)
    passages: list[IndexedPassage] = []
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        for p in doc.passages:
            counts = Counter(tokenize(p.text))
            doc_freq.update(counts.keys())
            passages.append(
                IndexedPassage(
                    passage_id=p.passage_id,
                    doc_id=p.doc_id,
                    title=p.title,
                    lang=p.lang,
                    text=p.text,
                    term_counts=dict(sorted(counts.items())),
                )
            )
    return Index(
        passages=tuple(passages),
        doc_freq=dict(sorted(doc_freq.items())),
        doc_count=len(docs),
        synthetic_doc_count=sum(1 for d in docs if d.synthetic),
    )


def write_index(index: Index, index_path: str | Path) -> None:
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": INDEX_FORMAT_VERSION,
        "doc_count": index.doc_count,
        "synthetic_doc_count": index.synthetic_doc_count,
        "doc_freq": index.doc_freq,
        "passages": [
            {
                "passage_id": p.passage_id,
                "doc_id": p.doc_id,
                "title": p.title,
                "lang": p.lang,
                "text": p.text,
                "term_counts": p.term_counts,
            }
            for p in index.passages
        ],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=1)
        fh.write("\n")


def read_index(index_path: str | Path) -> Index:
    path = Path(index_path)
    if not path.is_file():
        raise IndexError_(f"no index at {path} — run `cairn index` first")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("format_version") != INDEX_FORMAT_VERSION:
        raise IndexError_(
            f"{path}: index format {payload.get('format_version')!r} is not "
            f"{INDEX_FORMAT_VERSION}; re-run `cairn index`"
        )
    return Index(
        passages=tuple(
            IndexedPassage(
                passage_id=p["passage_id"],
                doc_id=p["doc_id"],
                title=p["title"],
                lang=p["lang"],
                text=p["text"],
                term_counts=p["term_counts"],
            )
            for p in payload["passages"]
        ),
        doc_freq=payload["doc_freq"],
        doc_count=payload["doc_count"],
        synthetic_doc_count=payload["synthetic_doc_count"],
    )


def build_and_write(corpus_dir: str | Path, index_path: str | Path) -> BuildReport:
    index = build_index(corpus_dir)
    write_index(index, index_path)
    return BuildReport(
        doc_count=index.doc_count,
        passage_count=index.passage_count,
        synthetic_doc_count=index.synthetic_doc_count,
        index_path=str(index_path),
    )
