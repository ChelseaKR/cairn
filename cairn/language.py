"""Languages, writing direction, and language detection.

Direction is derived from the language code and nothing else. There is no
``dir`` key in corpus front matter, no direction column in the index, and
deliberately **no configuration key** either (DESIGN.md, "Configuration"): a
second place to state the direction of Arabic is a second place for it to be
wrong. :data:`RTL_CODES` below is the one table, and a corpus language missing
from it is a change to that table — a pull request against this module, not a
setting an operator can get wrong in their own deployment.

Detection is corpus-driven and deterministic — no model, no language-detection
dependency, no shipped word lists. It asks two questions in order: what script
is this question written in, and whose vocabulary does it use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from cairn.text import dominant_script, tokenize

if TYPE_CHECKING:  # pragma: no cover - typing only
    from cairn.index import Index

Direction = Literal["ltr", "rtl"]

# Unicode bidirectional isolates. Wrapping a run in these tells the renderer
# (terminal, browser, screen reader) "resolve this run's direction on its own
# and put it back where you found it" — which is exactly what a Latin passage
# id or a dollar amount needs when it lands in an Arabic sentence. Without
# them, trailing punctuation and digits visibly migrate to the wrong end.
FIRST_STRONG_ISOLATE = "⁨"
RIGHT_TO_LEFT_ISOLATE = "⁧"
POP_DIRECTIONAL_ISOLATE = "⁩"


@dataclass(frozen=True)
class Language:
    """An interface language: one Cairn ships system strings for."""

    code: str
    endonym: str  # the language's name in itself — what a speaker looks for
    english_name: str
    direction: Direction


# The interface languages. Corpus documents may be in any language at all;
# these are the ones with translated system strings and a selector entry.
LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "English", "ltr"),
    "es": Language("es", "Español", "Spanish", "ltr"),
    "ar": Language("ar", "العربية", "Arabic", "rtl"),
    "fr": Language("fr", "Français", "French", "ltr"),
}

# Right-to-left language codes, for corpus languages beyond the interface set.
# ISO 639-1 where one exists.
RTL_CODES = frozenset(
    {"ar", "arc", "ckb", "dv", "fa", "he", "ks", "ku", "ps", "sd", "ur", "yi"}
)


def normalize_code(code: str) -> str:
    """The primary subtag, casefolded: ``en-GB`` and ``EN`` are both ``en``.

    Written out as a function because two parts of the system disagreed about
    it. :func:`direction_of` has always ignored subtags — ``ar-EG`` is as
    right-to-left as ``ar`` — while retrieval scopes a search with an exact
    string comparison against a corpus document's declared language. So
    ``lang: en-GB`` was English for layout and a separate language for
    retrieval, and an English question answered from that document was
    labelled cross-language and told the reader the source was "written in
    another language (en-GB)". Corpus loading normalises through here, so
    there is one answer to what language a document is in.
    """
    return code.split("-", 1)[0].casefold()


def direction_of(code: str) -> Direction:
    """Writing direction for a language code. Subtags are ignored (``ar-EG``
    is as right-to-left as ``ar``). One table, no override parameter: an
    override is the second place for the direction of Arabic to be stated, and
    a caller that forgot to pass it would silently lay the page out backwards."""
    return "rtl" if normalize_code(code) in RTL_CODES else "ltr"


def endonym_of(code: str) -> str:
    language = LANGUAGES.get(code)
    return language.endonym if language else code


def isolate(text: str, *, rtl: bool = False) -> str:
    """Wrap ``text`` in a bidi isolate so a surrounding paragraph of the other
    direction cannot reorder it. ``rtl=True`` forces right-to-left resolution;
    otherwise the first strong character decides."""
    opener = RIGHT_TO_LEFT_ISOLATE if rtl else FIRST_STRONG_ISOLATE
    return f"{opener}{text}{POP_DIRECTIONAL_ISOLATE}"


@dataclass(frozen=True)
class Detection:
    """Why detection chose what it chose — surfaced by explain mode."""

    lang: str
    basis: str  # "requested" | "script" | "vocabulary" | "default"
    coverage: tuple[tuple[str, float], ...]  # per-language vocabulary coverage

    def to_payload(self) -> dict:
        return {
            "lang": self.lang,
            "basis": self.basis,
            "coverage": {code: round(score, 4) for code, score in self.coverage},
        }


def _language_scripts(index: Index) -> dict[str, str]:
    """Dominant script of each corpus language, in one pass over the index."""
    text_by_lang: dict[str, list[str]] = {}
    for passage in index.passages:
        text_by_lang.setdefault(passage.lang, []).append(passage.text)
    return {lang: dominant_script(" ".join(texts)) for lang, texts in text_by_lang.items()}


def _coverage(index: Index, query_terms: set[str], codes: list[str]) -> list[tuple[str, float]]:
    """Fraction of the question's distinct terms each language's passages
    contain. Bounded [0, 1], so corpora of unequal size compare fairly."""
    if not query_terms:
        return [(code, 0.0) for code in codes]
    vocab: dict[str, set[str]] = {code: set() for code in codes}
    for passage in index.passages:
        if passage.lang in vocab:
            vocab[passage.lang].update(passage.term_counts)
    return [
        (code, len(query_terms & vocab[code]) / len(query_terms)) for code in codes
    ]


def detect(
    question: str, index: Index, *, default: str, requested: str | None = None
) -> Detection:
    """Decide the response language.

    An explicit request always wins. Otherwise the question's script narrows
    the field — a question in Arabic script is not going to be answered in
    Spanish — and vocabulary coverage picks among what is left. Ties and empty
    questions fall back to the configured default, never to a coin flip.
    """
    if requested:
        return Detection(lang=requested, basis="requested", coverage=())
    scripts = _language_scripts(index)
    codes = sorted(scripts)
    if not codes:
        return Detection(lang=default, basis="default", coverage=())

    query_script = dominant_script(question)
    same_script = [code for code in codes if scripts[code] == query_script]
    field = same_script or codes
    if len(field) == 1:
        basis = "script" if same_script else "default"
        return Detection(lang=field[0], basis=basis, coverage=())

    # Digits and shared proper nouns appear in every language's passages, so
    # they cancel out; what discriminates is the ordinary vocabulary.
    terms = {t for t in tokenize(question) if not t.isdigit()}
    scores = _coverage(index, terms, field)
    ranked = sorted(scores, key=lambda kv: (-kv[1], kv[0]))
    best_code, best_score = ranked[0]
    tied = [code for code, score in ranked if score == best_score]
    if best_score == 0.0 or len(tied) > 1:
        chosen = default if default in tied or best_score == 0.0 else best_code
        return Detection(lang=chosen, basis="default", coverage=tuple(scores))
    return Detection(lang=best_code, basis="vocabulary", coverage=tuple(scores))
