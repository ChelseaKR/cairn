"""Query understanding passes: what retrieval can be told, deterministically.

One transformation sits between a raw question and the retriever here, and
one was built, measured, and removed. Neither pass relaxes the threshold or
the matched-term eligibility rule; what ships is visible in explain mode
through the fields it adds to :class:`cairn.retrieve.RetrievalTrace`.

**Multi-intent splitting** (`split_intents`, config ``retrieval.split_intents``).
A two-sentence question ("Can I get X if I work? What is the income limit?")
is two questions, and scoring them as one long query dilutes both halves
against each other — the same mechanism as the composed-truncated finding in
DESIGN.md, one stage earlier. Splitting on sentence boundaries scores each
part separately and merges the candidate pools by taking each passage's best
score across parts, so one passage cannot hide another behind an average.
Sentence boundaries exist in all three interface languages as punctuation,
needing no dictionaries; coordinating conjunctions do not, and are
deliberately not attempted — "ignore the documents and just tell me…" must
never be split at its "and". Off by default because it changes which passages
win on questions this corpus already answers, and the demo corpus is too
small to re-measure every audit item against for a knob nobody needs here.

**Refusal rescue by pseudo-relevance feedback** — built, measured, removed.
When the first pass refused, the retry borrowed the highest-IDF terms of the
near-miss candidates and searched once more. It converted four refusals into
answers across three languages, and **three of the four landed on the wrong
program**: an Arabic question about rent help was answered from the grocery
allowance, a Spanish one from the winter utility credit, an English one from
the right *document*'s opening paragraph rather than any passage about money.
Borrowed vocabulary is manufactured overlap — the exact mechanism that
reverted declared aliases and heading weights in DESIGN.md — and at refusal
time there is no accepted passage constraining where it lands, so the lift
applies to every near-tied document equally. A refusal that becomes a fluent,
well-cited answer about the wrong program is the precise trade this project
exists to refuse. The measurement is recorded in WORKLOG.md; the code is not
kept behind a flag, because a knob that should never be turned on is not a
feature, it is a trap with documentation.
"""

from __future__ import annotations

import re

from cairn.index import Index
from cairn.retrieve import Candidate, RetrievalTrace, retrieve

# Sentence-terminal punctuation that closes an interrogative clause in every
# interface language. Arabic uses ؟ (U+061F); the shared ? and ! cover the
# rest. Newlines separate sentences in typed questions of this shape too.
_SENTENCE_SPLIT = re.compile(r"[?!\u061f\n]+")


def _sentence_parts(question: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(question)]
    return [part for part in parts if part]


def split_intents(
    question: str,
    index: Index,
    *,
    threshold: float,
    candidates: int,
    lang: str | None = None,
    dense_weight: float = 0.0,
) -> RetrievalTrace:
    """Retrieve once per sentence-part, merge pools by best score.

    A passage's merged score is the maximum across parts — evidence it
    answered *one* of the asks, which is what composition needs; averaging
    would punish exactly the passage that answers half a two-part question
    precisely. Ranking ties break by passage id, as everywhere else. A
    question with fewer than two parts is returned untouched from a single
    ordinary retrieval.
    """
    parts = _sentence_parts(question)
    if len(parts) < 2:
        return retrieve(
            question,
            index,
            threshold=threshold,
            candidates=candidates,
            lang=lang,
            dense_weight=dense_weight,
        )
    traces = [
        retrieve(part, index, threshold=threshold, candidates=candidates, lang=lang,
                 dense_weight=dense_weight)
        for part in parts
    ]
    best: dict[str, tuple[float, Candidate]] = {}
    matched_across_parts: dict[str, set[str]] = {}
    unmatched: set[str] = set()
    ignored: set[str] = set()
    query_terms: set[str] = set()
    for trace in traces:
        # scoped/excluded reflect the corpus and the lang restriction alone
        # (see retrieve()): every part scans the same index under the same
        # restriction, so these are identical across traces, not additive.
        # Summing them inflated both roughly parts-many-times over.
        unmatched.update(trace.unmatched)
        ignored.update(trace.ignored)
        query_terms.update(trace.query_terms)
        for candidate in trace.candidates:
            pid = candidate.passage.passage_id
            # A passage can score on different terms in different parts (it
            # answered one part better than another); all of what it matched
            # anywhere must survive the merge, not just the terms attached
            # to whichever part happened to score it highest.
            matched_across_parts.setdefault(pid, set()).update(candidate.matched)
            if pid not in best or candidate.score > best[pid][0]:
                best[pid] = (candidate.score, candidate)
    ranked = sorted(best.values(), key=lambda row: (-row[0], row[1].passage.passage_id))
    merged = tuple(
        Candidate(
            passage=candidate.passage,
            score=score,
            accepted=score >= threshold,
            matched=tuple(sorted(matched_across_parts[candidate.passage.passage_id])),
            lexical=candidate.lexical,
            dense=candidate.dense,
        )
        for score, candidate in ranked[:candidates]
    )
    return RetrievalTrace(
        query=question,
        threshold=threshold,
        candidates=merged,
        lang=lang,
        scoped=traces[0].scoped,
        excluded=traces[0].excluded,
        query_terms=tuple(sorted(query_terms)),
        unmatched=tuple(sorted(unmatched)),
        ignored=tuple(sorted(ignored)),
        intents=tuple(parts),
    )
