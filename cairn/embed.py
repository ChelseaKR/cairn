"""Deterministic hashed character-n-gram embeddings.

The semantic channel of hybrid retrieval. A passage and a question are
each mapped to a fixed-dimension sparse vector; their cosine is a subword
similarity score that fires where the lexical scorer cannot — misspellings
("allowence"), inflections the five-character truncation stemmer splits
("recibiendo" vs "recibe" past the stem cut), and cross-language cognates
("credito" vs "credit") whose shared surface the word-level index never sees.

Why this shape, given DESIGN.md's refusal of embeddings: what was refused was
a *trained* model — a dependency that must be downloaded, versioned, and run,
which ends offline-and-deterministic. These vectors are computed, not learned:

- **Feature hashing, not lookup.** Every n-gram hashes into one of 256 slots
  with a sign; no table of learned weights exists anywhere.
- **`hashlib.blake2b`, never `hash()`.** Python's builtin string hash is
  salted per process (`PYTHONHASHSEED`), so two runs would produce different
  vectors and identical questions would score differently. BLAKE2B with a
  fixed digest size and a namespaced personal string gives the same integer
  everywhere, forever.
- **Signed slots** (+1/-1 from one hash bit) halve the collision bias the
  hashing trick otherwise carries: colliding grams partially cancel instead
  of always adding.
- **Sublinear term frequency** (`1 + ln |count|`) matches the lexical
  scorer's stance that repetition is ever-weaker evidence.
- **L2-normalized output**, so cosine is bounded [0, 1] and can be fused with
  the bounded lexical score without breaking the threshold contract.

What this channel deliberately cannot do: translate, paraphrase, or match
meaning with no shared surface at all. An Arabic question and an English
passage share no character n-grams unless they share a proper noun or number,
so the cross-language limitation documented in DESIGN.md stands — this module
widens recall *within* a language's orthography; it does not cross languages.

The dimension is small because the demo corpus is small; at this size the
collision behavior between distinct trigrams is measured in
`tests/test_embed.py` rather than asserted away.
"""

from __future__ import annotations

import hashlib
import math

from cairn.text import _WORD_RE

# Vector width. Small enough that scoring stays cheap for a laptop-scale
# corpus, large enough that the demo corpus's distinct n-grams collide rarely;
# the test measures rather than trusts the constant.
DIMENSION = 256

# Character n-gram widths extracted per word. Two sizes catch both coarse
# shape (trigram) and slightly longer shared stems the truncation stemmer
# cuts differently.
NGRAM_SIZES = (3, 4)

# Word-boundary marker, wrapped around every word before grams are taken.
# Without it "bus" contributes the same interior grams inside "enthusiasm";
# with it, a gram's position within its word is part of the feature, which is
# most of what separates a real prefix from a coincidence.
_BOUNDARY = "\u2423"


def _words(text: str) -> list[str]:
    """Casefolded words under the same word grammar the tokenizer uses
    (word characters plus their combining marks), so a diacritic never splits
    a word into two half-features."""
    return [match.group(0).casefold() for match in _WORD_RE.finditer(text)]


def _digest(feature: str) -> int:
    """One stable unsigned integer per feature string."""
    return int.from_bytes(
        hashlib.blake2b(
            feature.encode("utf-8"), digest_size=8, person=b"cairn-embed"
        ).digest(),
        "big",
    )


def _slot(feature: str) -> tuple[int, float]:
    value = _digest(feature)
    return value % DIMENSION, 1.0 if (value >> 63) & 1 else -1.0


def features(text: str) -> dict[int, float]:
    """The embedding of ``text`` as ``{slot: weight}``, L2-normalized.

    Empty for text with no alphanumeric content — an empty vector has cosine
    0.0 against everything, which is exactly right for a question or passage
    this channel knows nothing about.
    """
    counts: dict[int, float] = {}
    for raw_word in _words(text):
        word = f"{_BOUNDARY}{raw_word}{_BOUNDARY}"
        for size in NGRAM_SIZES:
            for start in range(0, max(1, len(word) - size + 1)):
                slot, sign = _slot(word[start : start + size])
                counts[slot] = counts.get(slot, 0.0) + sign
    if not counts:
        return {}
    # Sublinear damping of the signed sums, then L2 normalize: a gram repeated
    # many times must not own the vector's direction outright. A slot whose
    # signs cancelled to exactly zero carries no evidence and is dropped.
    vector = {
        slot: math.copysign(1.0 + math.log(abs(count)), count)
        for slot, count in counts.items()
        if count != 0.0
    }
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    if norm == 0.0:
        return {}
    return {slot: weight / norm for slot, weight in vector.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    """Cosine of two L2-normalized sparse vectors, bounded [0, 1].

    Negative inner products mean opposing directions — evidence against, not
    absence of evidence, and only the latter may reach the threshold gate, so
    they clamp to zero here.
    """
    if not a or not b:
        return 0.0
    if len(b) < len(a):
        a, b = b, a
    dot = 0.0
    for slot, weight in a.items():
        other = b.get(slot)
        if other is not None:
            dot += weight * other
    return max(0.0, min(dot, 1.0))
