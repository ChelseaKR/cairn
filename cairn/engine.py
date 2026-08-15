"""The ask pipeline: language, retrieval, fallback, composition.

One entry point, :func:`ask`, shared by the CLI and the web interface so the
two can never drift into answering differently. It is the only place that
decides what language to answer in, and it decides in this order:

1. An explicit request wins. The interface always sends one, so a person who
   picked a language from the selector is never second-guessed.
2. Otherwise the question is examined against the corpus (see
   :mod:`cairn.language`).

Retrieval is then restricted to that language. If nothing in that language
clears the threshold, and configuration allows it, the search widens to the
whole corpus: an agency's translated material always lags its original
material, and the honest response to "we only have this in English" is to say
so in the language the person asked in and then quote the English exactly as
published. Translating a policy amount would produce an unsourced number, and
this project does not do that.

Both retrieval attempts are kept, so explain mode can show the widening
happening instead of presenting the second attempt as if it were the first.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn.answer import Answer, compose
from cairn.config import Config
from cairn.index import Index
from cairn.language import LANGUAGES, Detection, detect, direction_of, endonym_of, isolate
from cairn.messages import text as message
from cairn.retrieve import RetrievalTrace, retrieve


class EngineError(ValueError):
    """The request cannot be served as asked (e.g. an unknown language)."""


@dataclass(frozen=True)
class Attempt:
    """One pass of retrieval, and the scope it searched."""

    scope: str  # "language" (restricted) or "corpus" (widened fallback)
    trace: RetrievalTrace

    def to_payload(self) -> dict:
        return {
            "scope": self.scope,
            "lang": self.trace.lang,
            "excluded": self.trace.excluded,
            "grounded": self.trace.grounded,
        }


@dataclass(frozen=True)
class AskResult:
    answer: Answer
    detection: Detection
    attempts: tuple[Attempt, ...]

    @property
    def lang(self) -> str:
        return self.answer.lang

    @property
    def cross_language(self) -> bool:
        return any(source.lang != self.answer.lang for source in self.answer.sources)


def available_languages(index: Index) -> tuple[str, ...]:
    """Languages that may be asked for: every interface language, plus any
    corpus language that has no interface strings of its own. An interface
    language with no corpus behind it is still answerable — it refuses, or
    cites another language's sources, in the right words."""
    return tuple(sorted(set(LANGUAGES) | set(index.language_codes)))


def ask(question: str, index: Index, cfg: Config, *, lang: str | None = None) -> AskResult:
    languages = available_languages(index)
    if lang is not None and lang not in languages:
        raise EngineError(
            f"unsupported language {lang!r}; this corpus and interface offer: "
            + ", ".join(languages)
        )

    detection = detect(question, index, default=cfg.default_lang, requested=lang)
    response_lang = detection.lang
    rtl = direction_of(response_lang) == "rtl"

    primary = retrieve(
        question,
        index,
        threshold=cfg.threshold,
        candidates=cfg.candidates,
        lang=response_lang,
    )
    attempts = [Attempt(scope="language", trace=primary)]
    chosen = primary
    if not primary.grounded and cfg.cross_language_fallback:
        widened = retrieve(
            question, index, threshold=cfg.threshold, candidates=cfg.candidates, lang=None
        )
        attempts.append(Attempt(scope="corpus", trace=widened))
        if widened.grounded:
            chosen = widened

    notice = None
    if chosen.grounded and chosen is not primary:
        source_lang = chosen.accepted[0].passage.lang
        notice = message(
            "cross_language_notice",
            response_lang,
            language=isolate(endonym_of(source_lang), rtl=rtl),
        )

    contact = cfg.contact_for(response_lang)
    refusal_text = message(
        "refusal", response_lang, contact=isolate(contact) if rtl else contact
    )
    answer = compose(
        chosen,
        max_passages=cfg.max_passages,
        refusal_text=refusal_text,
        lang=response_lang,
        notice=notice,
    )
    return AskResult(answer=answer, detection=detection, attempts=tuple(attempts))
