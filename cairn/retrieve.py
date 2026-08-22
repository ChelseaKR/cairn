"""Retrieval: TF-IDF cosine scoring with a threshold gate.

Scores are cosine similarity between TF-IDF vectors of the query and each
passage, so every score is bounded [0, 1] and the configured threshold is a
legible, corpus-independent knob (DESIGN.md, "Retrieval"). IDF is smoothed and
computed **within the passage's language**: ``log((N_lang + 1) / (df_lang + 1))
+ 1``, zero for a term the document-frequency floor suppressed
(:attr:`cairn.index.LanguageStats.suppressed`, which owns the floor and its
one exemption). Ties break by passage id so ranking is fully deterministic.

A retrieval may be restricted to one language. Restriction happens before
scoring, not after, so the reported candidate list is exactly what was
considered — an explain-mode trace that hid a filter would be a lie.

Every retrieval produces a :class:`RetrievalTrace`: each candidate with its
score and its accepted/rejected verdict at the threshold, plus an explicit
grounded/not-grounded determination. It is the substrate the operator explain
mode (spec R5) renders.

The trace also carries the **term evidence**: which of the question's words
each candidate actually contains, which words no scored passage contained at
all, and which were too common in every language searched to carry any signal.
A score on its own says a passage ranked low; the term evidence says *why*, and
those are different findings for an operator — a word the corpus has never
heard of is a coverage gap, a word suppressed as common is a scorer decision,
and a passage that matched only the question's weakest word is a passage the
question barely addresses. Every query term falls into exactly one of the three
sets.
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
    # Query terms this passage actually contains and that carried weight.
    # A candidate always has at least one, or it would not have scored.
    matched: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    threshold: float
    candidates: tuple[Candidate, ...]  # ranked: score desc, then passage id
    lang: str | None = None  # language restriction applied, if any
    scoped: int = 0  # passages actually scored
    excluded: int = 0  # passages the restriction removed before scoring
    # Term evidence, partitioning the question's distinct terms three ways.
    query_terms: tuple[str, ...] = ()  # every distinct term the question tokenized to
    unmatched: tuple[str, ...] = ()  # terms absent from every passage searched
    ignored: tuple[str, ...] = ()  # terms the corpus has but suppressed as too common

    @property
    def accepted(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.accepted)

    @property
    def grounded(self) -> bool:
        return any(c.accepted for c in self.candidates)

    @property
    def scoring_terms(self) -> tuple[str, ...]:
        """The terms that could have contributed: everything but the ignored."""
        return tuple(t for t in self.query_terms if t not in set(self.ignored))

    @property
    def margin(self) -> float | None:
        """The score gap between the top (accepted) candidate and the next
        candidate in rank order, accepted or not.

        `None` when nothing is accepted — there is no winner to have a
        margin — or when the top candidate is the only one scored at all,
        which has no runner-up to compare against.

        Purely diagnostic: `candidates` is already sorted and scored before
        this is computed, so reading it changes no accept/reject decision and
        nothing about `Answer`. A small margin does not mean an answer is
        wrong; it means the ranking that produced it was close, which is
        worth an operator's attention for the same reason DESIGN.md's two
        documented hard cases are: the GoPass cross-document near-tie
        (0.1965 vs. 0.1885, 0.008 apart, both accepted) and `ck-022`, where
        the entire ranking among four otherwise-tied passages is decided by
        one incidental word.
        """
        if not self.candidates or not self.candidates[0].accepted:
            return None
        if len(self.candidates) < 2:
            return None
        return self.candidates[0].score - self.candidates[1].score


def _idf(term: str, stats: LanguageStats) -> float:
    """Smoothed IDF within one language, zero for a suppressed term.

    Which terms are suppressed is `LanguageStats.suppressed` — the
    document-frequency floor and its one exemption, kept next to the table it
    reads. The exemption exists because the floor is a statement about a
    document-frequency distribution, and a language Cairn holds one passage of
    does not have one: every term in it appears in every passage, so the floor
    zeroes the entire language and no question can reach it.
    """
    if term in stats.suppressed:
        return 0.0
    df = stats.doc_freq.get(term, 0)
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


def _matched_terms(
    query_counts: dict[str, int], passage: IndexedPassage, stats: LanguageStats
) -> tuple[str, ...]:
    """Which of the question's terms this passage holds *and* scores on.

    A term the passage contains but that IDF suppressed is not evidence, so it
    is not reported as a match — it would tell an operator the passage was
    relevant on a word that contributed nothing.
    """
    return tuple(
        sorted(
            term
            for term in query_counts
            if passage.term_counts.get(term, 0) and _idf(term, stats) > 0.0
        )
    )


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

    scored: list[tuple[float, IndexedPassage, tuple[str, ...]]] = []
    matched_anywhere: set[str] = set()
    langs_scored: set[str] = set()
    excluded = 0
    scoped = 0
    for passage in index.passages:
        if lang is not None and passage.lang != lang:
            excluded += 1
            continue
        scoped += 1
        if not query_counts:
            continue
        stats = index.stats_for(passage.lang)
        langs_scored.add(passage.lang)
        matched = _matched_terms(query_counts, passage, stats)
        matched_anywhere.update(matched)
        score = _cosine(query_counts, passage, stats)
        if score > 0.0:
            scored.append((score, passage, matched))
    scored.sort(key=lambda row: (-row[0], row[1].passage_id))

    # Three disjoint sets, in priority order. A term that counted somewhere is
    # matched, whatever it did elsewhere. Of the rest, a zero IDF can only
    # happen to a term the corpus *has* — the document-frequency floor is what
    # suppressed it — so "too common" and "not there at all" are genuinely
    # different findings and the operator gets told which one this is. The
    # floor is per language, so a word can be a stopword in one and a content
    # word in the next; being suppressed anywhere it was searched is enough to
    # explain why it contributed nothing.
    ignored = tuple(
        sorted(
            term
            for term in query_counts
            if term not in matched_anywhere
            and any(_idf(term, index.stats_for(code)) == 0.0 for code in langs_scored)
        )
    )
    unmatched = tuple(sorted(set(query_counts) - matched_anywhere - set(ignored)))

    top = tuple(
        Candidate(passage=p, score=s, accepted=s >= threshold, matched=m)
        for s, p, m in scored[:candidates]
    )
    return RetrievalTrace(
        query=query,
        threshold=threshold,
        candidates=top,
        lang=lang,
        scoped=scoped,
        excluded=excluded,
        query_terms=tuple(sorted(query_counts)),
        unmatched=unmatched,
        ignored=ignored,
    )
