"""Retrieval: TF-IDF cosine scoring with a threshold gate.

Scores are cosine similarity between TF-IDF vectors of the query and each
passage, so every score is bounded [0, 1] and the configured threshold is a
legible, corpus-independent knob (DESIGN.md, "Retrieval"). IDF is smoothed:
``log((N + 1) / (df + 1)) + 1``. Ties break by passage id so ranking is
fully deterministic.

Every retrieval produces a :class:`RetrievalTrace` — each candidate with its
score and its accepted/rejected verdict at the threshold, plus an explicit
grounded/not-grounded determination. Milestone M1 consumes only the accepted
list; the trace itself is the substrate the operator explain mode (spec R5,
milestone M2) will render.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cairn.index import Index, IndexedPassage, tokenize


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

    @property
    def accepted(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.accepted)

    @property
    def grounded(self) -> bool:
        return any(c.accepted for c in self.candidates)


# Terms appearing in more than this fraction of passages carry no signal for
# a corpus this shaped ("the", "de", "per", ...) and are ignored entirely —
# document-frequency-based stopword suppression, which needs no per-language
# stopword lists and stays deterministic. Chosen after measured misses where
# repeated function words outweighed topical terms on the demo corpus.
MAX_DF_RATIO = 0.5


def _idf(term: str, index: Index) -> float:
    df = index.doc_freq.get(term, 0)
    if df > MAX_DF_RATIO * index.passage_count:
        return 0.0
    return math.log((index.passage_count + 1) / (df + 1)) + 1.0


def _weight(count: int, idf: float) -> float:
    # Sublinear TF: repeating a term is weaker evidence each time it repeats.
    return (1.0 + math.log(count)) * idf if count > 0 else 0.0


def _cosine(query_counts: dict[str, int], passage: IndexedPassage, index: Index) -> float:
    dot = 0.0
    q_norm_sq = 0.0
    for term, q_count in query_counts.items():
        idf = _idf(term, index)
        q_weight = _weight(q_count, idf)
        q_norm_sq += q_weight * q_weight
        p_count = passage.term_counts.get(term, 0)
        if p_count:
            dot += q_weight * _weight(p_count, idf)
    if dot == 0.0 or q_norm_sq == 0.0:
        return 0.0
    p_norm_sq = 0.0
    for term, p_count in passage.term_counts.items():
        p_weight = _weight(p_count, _idf(term, index))
        p_norm_sq += p_weight * p_weight
    return dot / (math.sqrt(q_norm_sq) * math.sqrt(p_norm_sq))


def retrieve(query: str, index: Index, *, threshold: float, candidates: int) -> RetrievalTrace:
    query_counts: dict[str, int] = {}
    for token in tokenize(query):
        query_counts[token] = query_counts.get(token, 0) + 1

    scored: list[tuple[float, IndexedPassage]] = []
    if query_counts:
        for passage in index.passages:
            score = _cosine(query_counts, passage, index)
            if score > 0.0:
                scored.append((score, passage))
    scored.sort(key=lambda pair: (-pair[0], pair[1].passage_id))

    top = tuple(
        Candidate(passage=p, score=s, accepted=s >= threshold) for s, p in scored[:candidates]
    )
    return RetrievalTrace(query=query, threshold=threshold, candidates=top)
