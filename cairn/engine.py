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

from cairn.answer import Answer, Source, compose
from cairn.config import Config
from cairn.index import Index
from cairn.language import LANGUAGES, Detection, detect, direction_of, endonym_of, isolate
from cairn.messages import text as message
from cairn.query import split_intents
from cairn.retrieve import RetrievalTrace, retrieve
from cairn.tabular import parse_count_query, render_row, run_count


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
    # Set only when a structured-table tool produced the answer instead of
    # passage retrieval (see cairn.tabular). Payload-ready: the CLI's --json
    # and the server attach it beside the answer so a consumer can tell
    # "counted from rows" from "quoted from passages".
    tool: dict | None = None

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


def _answer_from_tables(
    question: str, index: Index, cfg: Config, *, response_lang: str, detection: Detection
) -> AskResult | None:
    """The structured-tool path, or ``None`` to fall through to retrieval.

    Reached only when the parser bound a complete count query (see
    :func:`cairn.tabular.parse_count_query`), so falling through is the
    exceptional case — a column that turned out unreadable at run time — and
    not a second guessing round. A bound query that matches zero rows refuses
    outright rather than falling through: "how many programs over $100" got
    its answer ("none") from the table, and answering some adjacent *passage*
    instead would be answering a different question.
    """
    candidate_tables = tuple(
        t for t in index.tables
        if cfg.cross_language_fallback or t.lang == response_lang
    )
    if not candidate_tables:
        return None
    query = parse_count_query(question, candidate_tables)
    if query is None:
        return None
    executed = run_count(query, candidate_tables)
    if executed is None:
        return None
    table, matched = executed
    rtl = direction_of(response_lang) == "rtl"
    contact = cfg.contact_for(response_lang)
    refusal_text = message(
        "refusal", response_lang, contact=isolate(contact) if rtl else contact
    )
    trace = RetrievalTrace(query=question, threshold=cfg.threshold, candidates=())
    tool = {
        "op": query.op,
        "table": table.table_id,
        "column": query.column,
        "comparator": query.comparator,
        "value": query.value,
        "matched_rows": [f"{table.table_id}#{number}" for number in matched],
    }
    if not matched:
        return AskResult(
            answer=Answer(
                kind="refusal", text=refusal_text, sources=(), trace=trace,
                lang=response_lang,
            ),
            detection=detection,
            attempts=(),
            tool=tool,
        )
    rendered = {number: render_row(table, number) for number in matched}
    sources = tuple(
        Source(
            title=table.title,
            source_id=f"{table.table_id}#{number}",
            lang=table.lang,
            text=rendered[number],
        )
        for number in matched
    )
    notice = message(
        "table_count_notice",
        response_lang,
        count=len(matched),
        total=table.row_count,
        title=table.title,
    )
    if table.lang != response_lang:
        cross_notice = message(
            "cross_language_notice",
            response_lang,
            language=isolate(endonym_of(table.lang), rtl=rtl),
        )
        notice = f"{notice} {cross_notice}"
    return AskResult(
        answer=Answer(
            kind="grounded",
            text="\n\n".join(rendered[number] for number in matched),
            sources=sources,
            trace=trace,
            lang=response_lang,
            notice=notice,
        ),
        detection=detection,
        attempts=(),
        tool=tool,
    )


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

    if cfg.tables_enabled and index.tables:
        table_result = _answer_from_tables(
            question, index, cfg, response_lang=response_lang, detection=detection
        )
        if table_result is not None:
            return table_result

    # Query understanding pass, opt-in (see cairn.query). Splitting replaces
    # the primary search; a single-part question is returned from it
    # untouched, so the default path is byte-identical to plain retrieval.
    if cfg.split_intents:
        primary = split_intents(
            question,
            index,
            threshold=cfg.threshold,
            candidates=cfg.candidates,
            lang=response_lang,
            dense_weight=cfg.dense_weight,
        )
    else:
        primary = retrieve(
            question,
            index,
            threshold=cfg.threshold,
            candidates=cfg.candidates,
            lang=response_lang,
            dense_weight=cfg.dense_weight,
        )
    attempts = [Attempt(scope="language", trace=primary)]
    chosen = primary
    if not primary.grounded and cfg.cross_language_fallback:
        widened = retrieve(
            question,
            index,
            threshold=cfg.threshold,
            candidates=cfg.candidates,
            lang=None,
            dense_weight=cfg.dense_weight,
        )
        attempts.append(Attempt(scope="corpus", trace=widened))
        if widened.grounded:
            chosen = widened

    # The notice describes the passages that are actually quoted, which is the
    # slice composition will take — not the widening that went looking for
    # them. Two things were wrong with keying it on `chosen is not primary`.
    #
    # It was a proxy: "the widened pass won" happens to imply "the source is
    # in another language" only because a passage scores identically in both
    # passes, so a widened pass can never surface a response-language passage
    # the restricted pass did not already have. Nothing states that and nothing
    # tests it, and it stops being true the moment IDF becomes scope-relative.
    #
    # And it read one passage's language while `compose` quotes
    # `max_passages` of them. At `max_passages = 2` an Arabic questioner could
    # be handed a Spanish passage and an English one under a notice naming
    # Spanish alone and calling it "the only source" — two false statements in
    # a sentence whose entire job is to say what language the answer is in.
    used = chosen.accepted[:cfg.max_passages]
    foreign: list[str] = []
    for candidate in used:
        if candidate.passage.lang != response_lang and candidate.passage.lang not in foreign:
            foreign.append(candidate.passage.lang)
    notice = None
    if foreign:
        # Singular only when there is genuinely one source and it is foreign.
        key = (
            "cross_language_notice"
            if len(used) == 1
            else "cross_language_notice_partial"
        )
        notice = message(
            key,
            response_lang,
            language=", ".join(isolate(endonym_of(code), rtl=rtl) for code in foreign),
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
