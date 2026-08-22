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

The index also carries a **fingerprint of the corpus it was built from**, and
reading one requires naming the corpus it is supposed to describe. Without
that, editing a document and forgetting to re-index is silent and it is
silent in the worst direction: Cairn goes on quoting the text the index holds,
under a citation to a document that now says something else. Every other
failure in this system is loud, and this one produced a fluent, confident,
correctly-formatted answer that the cited source did not support.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from cairn.corpus import CorpusError, fingerprint, load_corpus
from cairn.text import tokenize

# 2 when per-language statistics replaced the corpus-wide ones; 3 when the
# corpus fingerprint was added. A format bump is how a version-2 index —
# which cannot prove it is current, because nothing recorded what it was built
# from — is refused rather than trusted.
INDEX_FORMAT_VERSION = 3

# A sha256 hex digest, which is the only thing `corpus.fingerprint` returns.
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")

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


class StaleIndexError(IndexError_):
    """The corpus on disk is not the corpus this index was built from.

    Separated from its parent so a caller can tell "there is no usable index"
    from "there is one and it describes a corpus that has since changed". The
    CLI treats both as exit 1; the distinction is for anyone importing this.
    """


@dataclass(frozen=True)
class IndexedPassage:
    passage_id: str
    doc_id: str
    title: str
    lang: str
    text: str
    term_counts: dict[str, int]


# Terms appearing in more than this fraction of a language's passages carry no
# signal ("the", "de", "من") and are ignored entirely. Document-frequency
# stopword suppression needs no per-language word lists and stays
# deterministic — but the fraction has to be measured per language, or a
# multilingual corpus dilutes every language's function words below the bar.
#
# It lives here, next to the statistics it reads, rather than in
# `cairn.retrieve` where it used to. The floor is a rule for interpreting a
# document-frequency table, and a table small enough that the rule says
# nothing is a property of the table (see `LanguageStats.suppressed`).
MAX_DF_RATIO = 0.5


@dataclass(frozen=True)
class LanguageStats:
    """Corpus statistics within one language."""

    passage_count: int
    doc_freq: dict[str, int]

    @cached_property
    def suppressed(self) -> frozenset[str]:
        """Terms the document-frequency floor removes from scoring.

        Empty when the floor would remove *every* term this language has,
        which is not a stopword list — it is a language nothing can retrieve.
        A document published in a language Cairn holds one passage of gives
        every one of its terms `df == passage_count`, so all of them clear
        `df > 0.5 * 1` and the passage scores exactly 0.0 against every
        question, including a question that quotes it word for word. Measured:
        a single Vietnamese paragraph added to the demo corpus was
        unreachable in Vietnamese, and unreachable through the cross-language
        fallback too, because the fallback scores each passage against its own
        language's statistics. Cairn would then tell a Vietnamese speaker it
        has no source and, if the widened search found one, that "the only
        source I have for this is written in another language" — with their
        language sitting in the corpus, indexed, cited nowhere.

        The narrow claim, and it is deliberately narrow: this restores
        *reachability*. It does not make document frequency work on a small
        corpus. A two-passage language still has the program's own name
        suppressed if both passages carry it, which is the same limitation
        `ck-022` documents at demo-corpus scale, and the answer to that one is
        a bigger corpus rather than a cleverer floor.
        """
        cut = MAX_DF_RATIO * self.passage_count
        over = frozenset(term for term, df in self.doc_freq.items() if df > cut)
        return frozenset() if len(over) == len(self.doc_freq) else over

    @cached_property
    def dilution_exempt(self) -> bool:
        """True when the exemption above actually fired for this language:
        every term this language has would clear the document-frequency
        ratio, so :attr:`suppressed` exempted all of them rather than
        suppress everything down to a 0.0 score.

        Kept separate from :attr:`suppressed` being empty, which is also true
        of the ordinary case where nothing needs suppressing — a corpus large
        and varied enough that no term repeats in more than half its
        language's passages. Only this property tells the two apart, which is
        the distinction `cairn lint` reports: a language reachable *because*
        nothing needs suppressing is fine; a language reachable *because the
        floor stood down* is one question away from the same trap at a bigger
        scale, per ``ck-022``.
        """
        if not self.doc_freq:
            return False
        cut = MAX_DF_RATIO * self.passage_count
        over = sum(1 for df in self.doc_freq.values() if df > cut)
        return over == len(self.doc_freq)


@dataclass(frozen=True)
class Index:
    passages: tuple[IndexedPassage, ...]
    languages: dict[str, LanguageStats]
    doc_count: int
    synthetic_doc_count: int
    corpus_fingerprint: str

    @property
    def passage_count(self) -> int:
        return len(self.passages)

    def __post_init__(self) -> None:
        """An index that scores has to be an index that adds up.

        Nothing checked this, and the failure was quiet and in the worst
        direction. Scoring is TF-IDF against per-language statistics, and
        `stats_for` used to fabricate an empty `LanguageStats` for a language
        it had never heard of. Empty statistics give *every* term an IDF of
        exactly 1.0 — `log((0+1)/(0+1)) + 1` — so a passage whose language is
        missing from the table is scored on raw term overlap with no
        document-frequency suppression at all: "the", "de" and "من" count as
        much as the program's name, and the passage lands far above a
        threshold calibrated against weighted scores. An ungrounded answer
        presented as grounded, from a corrupt or hand-edited index file, with
        no error anywhere.

        `build_index` cannot produce that — it derives the table from the
        passages — which is exactly why the invariant belongs here rather than
        there: what reaches this constructor from `read_index` is whatever is
        on disk.
        """
        missing = sorted({p.lang for p in self.passages} - set(self.languages))
        if missing:
            raise IndexError_(
                f"index has passages in {', '.join(missing)} and no statistics for "
                f"them. Scoring would give every term the same weight, and the "
                f"relevance threshold is calibrated against weighted scores. "
                f"Re-run `cairn index`."
            )
        seen: set[str] = set()
        for passage in self.passages:
            if passage.passage_id in seen:
                raise IndexError_(
                    f"duplicate passage id {passage.passage_id!r}: a citation to it "
                    f"resolves to whichever copy a reader guessed"
                )
            seen.add(passage.passage_id)
            if not passage.text.strip():
                raise IndexError_(
                    f"passage {passage.passage_id!r} has no text: an answer composed "
                    f"from it would cite a source and quote nothing"
                )
        # An unparseable fingerprint has to be an error and not a skipped
        # check. `""` matches no corpus, so `verify_against` would refuse it
        # anyway — but only if something got as far as calling it, and an
        # index that cannot say what it was built from should not be an index
        # at all. Checked here so a hand-edited file is refused at the door.
        if not FINGERPRINT.match(self.corpus_fingerprint):
            raise IndexError_(
                f"index carries no usable corpus fingerprint "
                f"({self.corpus_fingerprint!r}): nothing can then tell whether the "
                f"passages it quotes are still what the corpus says. "
                f"Re-run `cairn index`."
            )

    def verify_against(self, corpus_dir: str | Path) -> None:
        """Raise unless ``corpus_dir`` is the corpus this index was built from.

        The failure being caught is not exotic: edit a document, forget to
        re-index, ask a question. Cairn answers from the index, so it quotes
        the paragraph as it *was* and cites the document as it *is* — and
        every surface in this project, the inline marker, the sources list,
        the recorded evidence bundle, presents that as grounded. There is no
        other check anywhere that could notice, because everything downstream
        of the index agrees with the index.
        """
        try:
            live = fingerprint(corpus_dir)
        except CorpusError as exc:
            # Deliberately fail-closed, and this is the decision worth
            # arguing with. An index whose corpus is not on disk cannot be
            # shown to be current, and "cannot be shown to be current" is
            # exactly the state that produces a confident wrong quotation.
            # The cost is that shipping an index without its corpus is not a
            # supported deployment; `read_index(..., corpus_dir=None)` says so
            # in the call for anyone who wants it anyway.
            raise IndexError_(
                f"the index cannot be checked against its corpus: {exc}. Cairn "
                f"answers by quoting what the index holds and citing the document "
                f"it came from, and declines to do that when the document is not "
                f"there to be compared. Point `[corpus] path` at the corpus this "
                f"index was built from."
            ) from exc
        if live != self.corpus_fingerprint:
            raise StaleIndexError(
                f"the corpus at {corpus_dir} has changed since the index was "
                f"built (corpus {live[:12]}, index "
                f"{self.corpus_fingerprint[:12]}). Answering now would quote the "
                f"text the index holds and cite a document that no longer says "
                f"it. Re-run `cairn index`."
            )

    @property
    def language_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.languages))

    def stats_for(self, lang: str) -> LanguageStats:
        """Statistics for a language the index actually has. The empty
        fallback that used to live here is the defect described in
        :meth:`__post_init__`; the invariant makes the lookup total."""
        return self.languages[lang]


@dataclass(frozen=True)
class BuildReport:
    doc_count: int
    passage_count: int
    synthetic_doc_count: int
    languages: tuple[str, ...]
    index_path: str
    corpus_fingerprint: str


def build_index(corpus_dir: str | Path) -> Index:
    # Taken before the documents are read, so a document edited *during* the
    # build produces a fingerprint that does not match the finished index and
    # the next command says re-index. The other order records the edit as
    # already indexed when it may not be.
    corpus_fingerprint = fingerprint(corpus_dir)
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
        corpus_fingerprint=corpus_fingerprint,
    )


def write_index(index: Index, index_path: str | Path) -> None:
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": INDEX_FORMAT_VERSION,
        "corpus_fingerprint": index.corpus_fingerprint,
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


def read_index(index_path: str | Path, corpus_dir: str | Path | None) -> Index:
    """Read an index and check it still describes ``corpus_dir``.

    ``corpus_dir`` has no default on purpose. The staleness check used to be
    impossible; making it optional would have made it something a caller
    forgets, which is the same defect with a longer fuse — and this is a
    reference implementation, so "the caller forgets" means "an agency's
    deployment forgets". Every path that can answer a question therefore has
    to name the corpus it is answering about.

    Pass ``None`` to state, in the call, that there is no corpus here to check
    against and an unverifiable index is accepted. Nothing in Cairn does.
    """
    path = Path(index_path)
    if not path.is_file():
        raise IndexError_(f"no index at {path} — run `cairn index` first")
    # A generated file, so a malformed one means "re-run `cairn index`" and
    # not a traceback. `cairn.cli` catches IndexError_ and prints that advice;
    # a truncated write used to surface as a bare JSONDecodeError and a hand
    # edit as a KeyError, neither of which reached it.
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("format_version") != INDEX_FORMAT_VERSION:
            raise IndexError_(
                f"{path}: index format {payload.get('format_version')!r} is not "
                f"{INDEX_FORMAT_VERSION}; re-run `cairn index`"
            )
        index = Index(
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
            corpus_fingerprint=payload["corpus_fingerprint"],
        )
    except IndexError_:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise IndexError_(
            f"{path}: the index file is malformed ({type(exc).__name__}: {exc}); "
            f"re-run `cairn index`"
        ) from exc
    if corpus_dir is not None:
        index.verify_against(corpus_dir)
    return index


def build_and_write(corpus_dir: str | Path, index_path: str | Path) -> BuildReport:
    index = build_index(corpus_dir)
    write_index(index, index_path)
    return BuildReport(
        doc_count=index.doc_count,
        passage_count=index.passage_count,
        synthetic_doc_count=index.synthetic_doc_count,
        languages=index.language_codes,
        index_path=str(index_path),
        corpus_fingerprint=index.corpus_fingerprint,
    )
