"""Tokenization, script classification, and script-conditioned normalization.

One tokenizer serves every corpus language. Where a script genuinely needs
different handling, the handling keys off the *script of the characters*, not
off a configured language code — so a mixed-language passage normalizes
correctly and an operator never has to declare "this corpus is Arabic" for the
Arabic in it to be findable.
"""

from __future__ import annotations

import re

# A "word" is a run of word characters plus the combining marks that belong to
# them. Python's ``\w`` excludes nonspacing marks, which would split Arabic
# words at every diacritic (شهريًا -> شهري + ا) and quietly wreck retrieval, so
# the mark ranges for the scripts this project handles are added explicitly.
_MARKS = "".join(
    (
        "\u0300-\u036f",  # combining diacritical marks (Latin, Greek, Cyrillic)
        "\u0591-\u05bd\u05bf\u05c1-\u05c2",  # Hebrew points
        "\u0610-\u061a\u064b-\u065f\u0670",  # Arabic tashkeel and superscript alef
        "\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed",  # Quranic annotation marks
        "\u0640",  # tatweel (a stretching glyph, never a word boundary)
    )
)
_WORD_RE = re.compile(rf"[\w{_MARKS}]+", re.UNICODE)

# Truncation stemming: tokens are cut to their first STEM_LENGTH characters.
# A deliberately crude, fully deterministic, dictionary-free normalizer that
# unifies inflectional variants (month/monthly, deadline/deadlines,
# recibe/reciben) across suffixing languages without any per-language rules.
# Chosen after measured retrieval misses on the demo corpus caused exactly by
# such variants; the trade-off (occasional collisions like person/personal) is
# acceptable for a reference implementation.
STEM_LENGTH = 5

# Normalized tokens shorter than this are dropped before they can be scored.
# Document-frequency suppression handles function words that are *frequent in
# the corpus*, but a demo corpus is small enough that a question word can be
# rare in it and so score as highly discriminating: measured on this corpus,
# "ما"/"التي" and "es"/"la" alone pushed off-topic questions to within 0.02 of
# genuine ones. Short-token dropping is the language-neutral half of the fix —
# almost nothing carrying policy meaning is one or two characters long in any
# of the scripts here. Numbers are exempt: "$20" is exactly the kind of fact a
# benefits question turns on.
MIN_TERM_LENGTH = 3

# --- script classification -------------------------------------------------
#
# Enough resolution to answer the two questions Cairn actually asks: which
# script is this run of text written in (language detection), and does this
# script need normalization before stemming.

_ARABIC_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)
_HEBREW_RANGES = ((0x0590, 0x05FF), (0xFB1D, 0xFB4F))


def script_of(char: str) -> str:
    """``"arabic"``, ``"hebrew"``, ``"latin"``, or ``"other"``."""
    point = ord(char)
    for low, high in _ARABIC_RANGES:
        if low <= point <= high:
            return "arabic"
    for low, high in _HEBREW_RANGES:
        if low <= point <= high:
            return "hebrew"
    if char.isalpha():
        return "latin" if point < 0x0250 else "other"
    return "other"


def dominant_script(text: str) -> str:
    """The script most of ``text``'s letters are written in, ``"other"`` if
    there are no letters. Ties break by name so the result is deterministic."""
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        script = script_of(char)
        counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "other"
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


# --- Arabic normalization --------------------------------------------------
#
# Truncation stemming alone fails on Arabic script for a reason that has
# nothing to do with morphology being "non-suffixing": Arabic is written with
# optional diacritics and with clitics glued to the front of the word, so the
# same word reaches the tokenizer in several spellings and the definite
# article eats two of the five stem characters. These rules are deterministic,
# dictionary-free, and apply to any Arabic-script token regardless of the
# document's declared language.

_ARABIC_STRIP = re.compile("[\u064b-\u065f\u0670\u0640]")  # tashkeel + tatweel
_ARABIC_FOLD = str.maketrans(
    {
        "أ": "ا",  # alef with hamza above -> alef
        "إ": "ا",  # alef with hamza below -> alef
        "آ": "ا",  # alef with madda      -> alef
        "ٱ": "ا",  # alef wasla           -> alef
        "ى": "ي",  # alef maksura         -> yeh
        "ة": "ه",  # teh marbuta          -> heh
    }
)
# Clitics written joined to the following word; longest first, one strip per
# token. Stripping the single-letter preposition "ل" matters more than it
# looks: without it "لمخصص" and "مخصص" are different terms and a question
# about a program does not match the document describing it. The rule is
# deliberately blunt and will sometimes shorten a word that merely starts with
# these letters — harmless for a lexical scorer, because the question is
# normalized by exactly the same rule as the document.
_ARABIC_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال", "ل")
_ARABIC_MIN_STEM = 3


def normalize_arabic(token: str) -> str:
    token = _ARABIC_STRIP.sub("", token).translate(_ARABIC_FOLD)
    for prefix in _ARABIC_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= _ARABIC_MIN_STEM:
            return token[len(prefix) :]
    return token


def normalize(token: str) -> str:
    """Casefold, script-normalize, truncation-stem. Returns ``""`` for a token
    that carries no retrieval signal, which the caller drops."""
    token = token.casefold()
    if any(script_of(char) == "arabic" for char in token):
        token = normalize_arabic(token)
    token = token[:STEM_LENGTH]
    if len(token) < MIN_TERM_LENGTH and not token.isdigit():
        return ""
    return token


def tokenize(text: str) -> list[str]:
    """Unicode word tokens, normalized, with signal-free tokens dropped.
    Language-agnostic by construction."""
    tokens = (normalize(m.group(0)) for m in _WORD_RE.finditer(text))
    return [token for token in tokens if token]
