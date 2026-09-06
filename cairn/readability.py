"""Plain-language readability, measured per passage, absent where unsupported.

Cairn quotes passages verbatim, so the reading level of an answer *is* the
reading level of the corpus. A public agency is held to plain-language
obligations for exactly this text, and nothing in this repository measured it.

Two rules shape what is here.

**A grade is computed, never asserted.** Each formula is named, published, and
implemented in full below with its coefficients in the open, so a reader can
check the arithmetic against the paper rather than take a number on trust.

**A language with no formula in force reports ``n/a``, never a number.** The
formulas here were fitted on English and Spanish text and their coefficients
mean nothing outside them. Running the English one over Arabic would produce a
grade with the right shape and no referent, which is the failure this project
refuses everywhere else: an absence rendered as a value. An operator who
decides a formula is close enough for another language may say so in
``[lint.readability]``, and then the number is theirs and is labelled with the
formula it came from.

What this cannot do, stated plainly because a grade invites more confidence
than it earns:

* **Syllable counting is a heuristic, not a lexicon.** Spanish is counted by
  vowel groups, which is close to right for a language whose orthography is
  nearly phonemic, and wrong at hiatus (``rí-o`` is two syllables, counted as
  one). English is counted by vowel groups with a silent-final-``e`` rule,
  which is the standard heuristic and is wrong on a long tail of words. Both
  are deterministic, dictionary-free, and stated here rather than in a
  footnote.
* **A grade is not a judgement.** A low grade over a passage that answers the
  wrong question is not a good passage. Readability is a corpus fact an
  operator can act on by asking the agency for a plain-language page; it is
  not a score of the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cairn.text import SENTENCE_END

# Words, for counting: a run of letters, apostrophes and hyphens. Deliberately
# not ``cairn.text.tokenize``, which stems, drops short tokens and normalizes
# Arabic. Those are the right rules for *retrieval*, and the wrong ones for a
# word count: a formula fitted on running prose needs the words the author
# wrote, including "a" and "the".
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)

_EN_VOWELS = "aeiouy"
# Spanish vowels: the five, their accented forms, and u-diaeresis. ``y`` is
# deliberately absent. In Spanish it is a vowel only standing alone ("y") or
# closing a word ("muy", "ley"); anywhere else it is a consonant, and counting
# it as a vowel merges the syllable it opens into the one before
# ("a-yu-da" measured as two syllables instead of three). ``syllables_es``
# handles the two vowel positions explicitly.
_ES_VOWELS = "aeiouáéíóúü"

FLESCH_KINCAID_GRADE = "flesch_kincaid_grade"
CRAWFORD_GRADE = "crawford_grade"

FORMULA_SOURCES: dict[str, str] = {
    FLESCH_KINCAID_GRADE: (
        "Flesch-Kincaid grade level: Kincaid, Fishburne, Rogers and Chissom "
        "(1975), Derivation of New Readability Formulas for Navy Enlisted "
        "Personnel, Research Branch Report 8-75. "
        "0.39 x (words / sentences) + 11.8 x (syllables / words) - 15.59"
    ),
    CRAWFORD_GRADE: (
        "Crawford grade level for Spanish: Crawford (1985), Fórmula y gráfico "
        "para determinar la comprensibilidad de textos de nivel primario en "
        "castellano, Lectura y Vida 6(4). "
        "-0.205 x (sentences per 100 words) + 0.049 x (syllables per 100 "
        "words) - 3.407"
    ),
}

# The languages a formula is in force for with no configuration at all. Both
# formulas were fitted on the language they are listed under; neither is
# extended to a third language here, because extending it is a claim about
# text this project has not measured.
BUILTIN_FORMULAS: dict[str, str] = {
    "en": FLESCH_KINCAID_GRADE,
    "es": CRAWFORD_GRADE,
}


class ReadabilityError(ValueError):
    """A formula was named that this module does not implement."""


def formula_for(lang: str, overrides: dict[str, str] | None = None) -> str:
    """The formula in force for ``lang``, or ``""`` when there is none.

    An operator's ``[lint.readability]`` entry wins over the built-in table,
    including for ``en`` and ``es``: deciding which published formula to hold
    a corpus to is the operator's call, not this module's.
    """
    if overrides and lang in overrides:
        return overrides[lang]
    return BUILTIN_FORMULAS.get(lang, "")


def validate_formulas(overrides: dict[str, str]) -> None:
    """Refuse a configured formula name this module cannot compute.

    Checked where the configuration is made rather than where a passage is
    measured, so a typo in ``cairn.toml`` is a refusal at load time and not a
    language that silently reports ``n/a`` forever.
    """
    for lang, name in sorted(overrides.items()):
        if name not in FORMULA_SOURCES:
            raise ReadabilityError(
                f"lint.readability.{lang} names {name!r}, which is not a formula "
                f"this build implements ({', '.join(sorted(FORMULA_SOURCES))}). "
                f"A formula that cannot be computed would report 'n/a' for this "
                f"language forever while the configuration says otherwise."
            )


def sentences(text: str) -> int:
    """How many sentences the text holds, by the one sentence rule this
    repository has: ``cairn.text.SENTENCE_END``, which ``cairn.stream`` uses
    to chunk an answer. Text with no terminal punctuation is one sentence,
    not zero; text with nothing in it is zero."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len([part for part in SENTENCE_END.split(stripped) if part.strip()])


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def _vowel_groups(word: str, vowels: str) -> int:
    count = 0
    previous_was_vowel = False
    for char in word:
        is_vowel = char in vowels
        if is_vowel and not previous_was_vowel:
            count += 1
        previous_was_vowel = is_vowel
    return count


def syllables_en(word: str) -> int:
    """Vowel groups, less a silent final ``e``, at least one.

    The standard heuristic, and standard-heuristic wrong on words like
    "queue" and "poem". It is deterministic and dictionary-free, which is
    what keeps the number reproducible from the commit.
    """
    lowered = word.lower()
    count = _vowel_groups(lowered, _EN_VOWELS)
    if lowered.endswith("e") and not lowered.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(count, 1)


def syllables_es(word: str) -> int:
    """Vowel groups, at least one, with ``y`` a vowel only where it is one.

    Spanish orthography is close to phonemic, so vowel groups are close to
    syllables. It is wrong at hiatus: ``río`` is two syllables and counts as
    one, and ``leer`` is two and counts as one. No diphthong table is applied,
    because applying half of one would be less predictable than applying none.
    """
    lowered = word.lower()
    if lowered == "y":
        return 1
    # A final ``y`` closes the vowel group it sits in ("muy", "ley"); every
    # other ``y`` opens a syllable and is a consonant here.
    body = lowered[:-1].replace("y", "\u0000") + lowered[-1:] if lowered else lowered
    return max(_vowel_groups(body, _ES_VOWELS + "y"), 1)


_SYLLABLE_COUNTERS = {
    FLESCH_KINCAID_GRADE: syllables_en,
    CRAWFORD_GRADE: syllables_es,
}


@dataclass(frozen=True)
class Measurement:
    """What one passage's text came to under the formula in force for it."""

    lang: str
    formula: str
    """The formula applied, or ``""`` when none is in force for this language."""
    words: int
    sentences: int
    syllables: int
    grade: float | None
    """The grade level, or ``None``. ``None`` is never rendered as a number."""
    reason: str
    """Why there is no grade, or ``""`` when there is one."""

    @property
    def mean_sentence_length(self) -> float | None:
        if not self.sentences:
            return None
        return self.words / self.sentences

    def describe(self) -> str:
        """One line, in which an absent grade says so rather than reading 0."""
        if self.grade is None:
            return f"n/a ({self.reason})"
        length = self.mean_sentence_length
        assert length is not None  # a grade implies at least one sentence
        return (
            f"grade {self.grade:.1f} ({self.formula}); "
            f"{self.words} word(s), {self.sentences} sentence(s), "
            f"mean sentence length {length:.1f}"
        )


def _grade_for(
    formula: str, word_count: int, sentence_count: int, syllable_count: int
) -> float:
    per_sentence = word_count / sentence_count
    per_word = syllable_count / word_count
    if formula == FLESCH_KINCAID_GRADE:
        return 0.39 * per_sentence + 11.8 * per_word - 15.59
    # Crawford is expressed per 100 words, so both terms are scaled there
    # rather than the coefficients being pre-divided here: the numbers below
    # are the ones printed in the paper.
    sentences_per_100 = 100 / per_sentence
    syllables_per_100 = 100 * per_word
    return -0.205 * sentences_per_100 + 0.049 * syllables_per_100 - 3.407


def measure(text: str, lang: str, overrides: dict[str, str] | None = None) -> Measurement:
    """Measure one passage. Every path that cannot produce a grade says why."""
    formula = formula_for(lang, overrides)
    found = words(text)
    sentence_count = sentences(text)
    if not formula:
        return Measurement(
            lang=lang,
            formula="",
            words=len(found),
            sentences=sentence_count,
            syllables=0,
            grade=None,
            reason=f"no formula in force for {lang}",
        )
    counter = _SYLLABLE_COUNTERS[formula]
    syllable_count = sum(counter(word) for word in found)
    if not found:
        # Not a grade of zero. A formula whose denominator is empty has
        # nothing to divide, and zero is a reading level a passage could
        # plausibly have. (The other denominator cannot be empty here: any
        # word at all makes the stripped text non-empty, which is one
        # sentence.)
        return Measurement(
            lang=lang,
            formula=formula,
            words=0,
            sentences=sentence_count,
            syllables=syllable_count,
            grade=None,
            reason="no words to measure",
        )
    return Measurement(
        lang=lang,
        formula=formula,
        words=len(found),
        sentences=sentence_count,
        syllables=syllable_count,
        grade=_grade_for(formula, len(found), sentence_count, syllable_count),
        reason="",
    )


@dataclass(frozen=True)
class LanguageSummary:
    """A corpus's passages in one language, and what they came to."""

    lang: str
    formula: str
    passages: int
    graded: int
    mean_grade: float | None
    max_grade: float | None
    reason: str

    def describe(self) -> str:
        if self.mean_grade is None or self.max_grade is None:
            return f"[{self.lang}] {self.passages} passage(s): n/a ({self.reason})"
        return (
            f"[{self.lang}] {self.passages} passage(s), {self.graded} graded "
            f"by {self.formula}: mean grade {self.mean_grade:.1f}, "
            f"highest {self.max_grade:.1f}"
        )


def summarize(measurements: list[tuple[str, Measurement]]) -> list[LanguageSummary]:
    """Per-language summary rows, in language order.

    A language whose passages produced no grade at all reports the reason its
    passages gave, so a summary line never carries a mean over an empty set.
    """
    by_language: dict[str, list[Measurement]] = {}
    for _, measurement in measurements:
        by_language.setdefault(measurement.lang, []).append(measurement)
    rows: list[LanguageSummary] = []
    for lang in sorted(by_language):
        found = by_language[lang]
        graded = [item.grade for item in found if item.grade is not None]
        formula = found[0].formula
        rows.append(
            LanguageSummary(
                lang=lang,
                formula=formula,
                passages=len(found),
                graded=len(graded),
                mean_grade=sum(graded) / len(graded) if graded else None,
                max_grade=max(graded) if graded else None,
                reason="" if graded else found[0].reason,
            )
        )
    return rows
