"""On-disk index: build, write, read.

The index is one JSON file holding passage records, per-passage term counts,
and per-language corpus statistics. Serialization uses sorted keys, a fixed
key order, and no timestamps, so re-indexing an unchanged corpus produces a
byte-identical file — idempotency (spec R1) is checkable with a file hash.

Statistics are kept **per language**, not corpus-wide. Document frequency is
how Cairn suppresses function words without shipping stopword lists, and
"appears in most passages" is only meaningful within one language: once a
corpus holds three languages, no language's function words can appear in half
of it, and every one of them sails through a corpus-wide ratio. Measured on
the demo corpus, that single bug cost Arabic retrieval roughly a third of its
score on every question.

Scores are computed at query time from the stored counts; for corpora sized
for a laptop demo there is nothing to precompute.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cairn.corpus import load_corpus
from cairn.text import tokenize

# Bumped to 2 when per-language statistics replaced the corpus-wide ones.
INDEX_FORMAT_VERSION = 2

# How heavily a document's title counts toward its passages, as a repetition
# factor. A title is the most topical sentence a policy document has, and
# folded in once it is diluted among sixty body words. Measured on the demo
# corpus: at weight 1 a Spanish question naming one program ("cuanto tarda la
# decision del subsidio de alimentos") was answered from another program's
# document, because that document's heading happened to contain the question's
# process words. Raising the weight to 5 puts every probe's fact passage at
# rank 1, widens the calibration gap from 0.187/0.148 to 0.196/0.122, and
# fixes the cross-language disagreements the audit found. Weights above 5
# changed nothing measurable, so 5 is where it stops.
TITLE_WEIGHT = 5


class IndexError_(ValueError):
    """The index file is missing, unreadable, or from another format version."""


@dataclass(frozen=True)
class IndexedPassage:
    passage_id: str
    doc_id: str
    title: str
    lang: str
    text: str
    term_counts: dict[str, int]


@dataclass(frozen=True)
class LanguageStats:
    """Corpus statistics within one language."""

    passage_count: int
    doc_freq: dict[str, int]


@dataclass(frozen=True)
class Index:
    passages: tuple[IndexedPassage, ...]
    languages: dict[str, LanguageStats]
    doc_count: int
    synthetic_doc_count: int

    @property
    def passage_count(self) -> int:
        return len(self.passages)

    @property
    def language_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.languages))

    def stats_for(self, lang: str) -> LanguageStats:
        return self.languages.get(lang) or LanguageStats(passage_count=0, doc_freq={})


@dataclass(frozen=True)
class BuildReport:
    doc_count: int
    passage_count: int
    synthetic_doc_count: int
    languages: tuple[str, ...]
    index_path: str


def build_index(corpus_dir: str | Path) -> Index:
    docs = load_corpus(corpus_dir)
    passages: list[IndexedPassage] = []
    doc_freq: dict[str, Counter[str]] = {}
    passage_counts: Counter[str] = Counter()
    for doc in docs:
        for p in doc.passages:
            # The document title is scored into every one of its passages,
            # weighted (see TITLE_WEIGHT). A passage lifted out of the middle
            # of a policy document loses the one sentence that says what the
            # document is about, and questions name the program ("the grocery
            # allowance", "el crédito de invierno") far more reliably than
            # they quote its body. Measured on the demo corpus, indexing
            # titles at all was the single largest retrieval improvement of
            # the multilingual milestone. Only the body text is ever quoted
            # back in an answer.
            counts = Counter(tokenize(f"{p.title}\n" * TITLE_WEIGHT + p.text))
            doc_freq.setdefault(p.lang, Counter()).update(counts.keys())
            passage_counts[p.lang] += 1
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
    languages = {
        lang: LanguageStats(
            passage_count=passage_counts[lang], doc_freq=dict(sorted(doc_freq[lang].items()))
        )
        for lang in sorted(doc_freq)
    }
    return Index(
        passages=tuple(passages),
        languages=languages,
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
        "languages": {
            lang: {"passage_count": stats.passage_count, "doc_freq": stats.doc_freq}
            for lang, stats in index.languages.items()
        },
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
        languages={
            lang: LanguageStats(
                passage_count=stats["passage_count"], doc_freq=stats["doc_freq"]
            )
            for lang, stats in payload["languages"].items()
        },
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
        languages=index.language_codes,
        index_path=str(index_path),
    )
