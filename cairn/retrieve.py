"""Retrieval: TF-IDF cosine scoring with a threshold gate.

Scores are cosine similarity between TF-IDF vectors of the query and each
passage, so every score is bounded [0, 1] and the configured threshold is a
legible, corpus-independent knob (DESIGN.md, "Retrieval"). IDF is smoothed and
computed **within the passage's language**: ``log((N_lang + 1) / (df_lang + 1))
+ 1``. Ties break by passage id so ranking is fully deterministic.

A retrieval may be restricted to one language. Restriction happens before
scoring, not after, so the reported candidate list is exactly what was
considered — an explain-mode trace that hid a filter would be a lie.

Every retrieval produces a :class:`RetrievalTrace`: each candidate with its
score and its accepted/rejected verdict at the threshold, plus an explicit
grounded/not-grounded determination. It is the substrate the operator explain
mode (spec R5) renders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cairn.index import Index, IndexedPassage, LanguageStats
from cairn.text import tokenize


@dataclass(frozen=True)
class Candidate:
    passage: IndexedPassage
    score: float
    accepted: bool


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    threshold: float
    candidates: tuple[Candidate, ...]  # ranked: score desc, then passage id
    lang: str | None = None  # language restriction applied, if any
    scoped: int = 0  # passages actually scored
    excluded: int = 0  # passages the restriction removed before scoring

    @property
    def accepted(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.accepted)

    @property
    def grounded(self) -> bool:
        return any(c.accepted for c in self.candidates)


# Terms appearing in more than this fraction of a language's passages carry no
# signal ("the", "de", "من") and are ignored entirely. Document-frequency
# stopword suppression needs no per-language word lists and stays
# deterministic — but the fraction has to be measured per language, or a
# multilingual corpus dilutes every language's function words below the bar.
MAX_DF_RATIO = 0.5


def _idf(term: str, stats: LanguageStats) -> float:
    df = stats.doc_freq.get(term, 0)
    if df > MAX_DF_RATIO * stats.passage_count:
        return 0.0
    return math.log((stats.passage_count + 1) / (df + 1)) + 1.0


def _weight(count: int, idf: float) -> float:
    # Sublinear TF: repeating a term is weaker evidence each time it repeats.
    return (1.0 + math.log(count)) * idf if count > 0 else 0.0


def _cosine(
    query_counts: dict[str, int], passage: IndexedPassage, stats: LanguageStats
) -> float:
    dot = 0.0
    q_norm_sq = 0.0
    for term, q_count in query_counts.items():
        idf = _idf(term, stats)
        q_weight = _weight(q_count, idf)
        q_norm_sq += q_weight * q_weight
        p_count = passage.term_counts.get(term, 0)
        if p_count:
            dot += q_weight * _weight(p_count, idf)
    if dot == 0.0 or q_norm_sq == 0.0:
        return 0.0
    p_norm_sq = 0.0
    for term, p_count in passage.term_counts.items():
        p_weight = _weight(p_count, _idf(term, stats))
        p_norm_sq += p_weight * p_weight
    if p_norm_sq == 0.0:
        return 0.0
    return dot / (math.sqrt(q_norm_sq) * math.sqrt(p_norm_sq))


def retrieve(
    query: str,
    index: Index,
    *,
    threshold: float,
    candidates: int,
    lang: str | None = None,
) -> RetrievalTrace:
    query_counts: dict[str, int] = {}
    for token in tokenize(query):
        query_counts[token] = query_counts.get(token, 0) + 1

    scored: list[tuple[float, IndexedPassage]] = []
    excluded = 0
    scoped = 0
    for passage in index.passages:
        if lang is not None and passage.lang != lang:
            excluded += 1
            continue
        scoped += 1
        if not query_counts:
            continue
        score = _cosine(query_counts, passage, index.stats_for(passage.lang))
        if score > 0.0:
            scored.append((score, passage))
    scored.sort(key=lambda pair: (-pair[0], pair[1].passage_id))

    top = tuple(
        Candidate(passage=p, score=s, accepted=s >= threshold) for s, p in scored[:candidates]
    )
    return RetrievalTrace(
        query=query,
        threshold=threshold,
        candidates=top,
        lang=lang,
        scoped=scoped,
        excluded=excluded,
    )
