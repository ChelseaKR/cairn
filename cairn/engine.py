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

Retrieval is scoped a second way when the corpus is layered by jurisdiction
(:mod:`cairn.jurisdiction`). A county deployment's corpus is federal pages
plus state pages plus its own, and the applicable rule is the most specific
one that exists — so the search runs one layer at a time, county first, and
stops at the first layer that clears the threshold. An answer from a wider
layer carries a notice saying which layer it came from, in the asker's
language, exactly as the cross-language fallback does; with
``cross_jurisdiction_fallback = false`` it refuses instead.

Jurisdiction is the outer loop and language the inner one, deliberately.
Being answered from the wrong county is a wrong answer; being answered from
the right county in the wrong language is a correct answer that says so. So
the county's own page in English beats the state's page in the asker's
language, and both are disclosed.

The structured-table tool does not run while a jurisdiction is in force.
Corpus tables carry no jurisdiction — they are CSV files, with no front
matter to put one in — and this module's rule for a source that does not say
where it applies is that it has not said it applies here. A count computed
over a statewide table and handed to a county resident with nothing said is
the same defect as a passage quoted from the wrong county, arriving through
the one path that never quotes a passage. Such a question falls through to
passage retrieval, which answers or refuses in the ordinary way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.answer import Answer, Source, compose
from cairn.config import Config
from cairn.index import Index
from cairn.jurisdiction import CODE as JURISDICTION_CODE
from cairn.jurisdiction import ladder
from cairn.language import LANGUAGES, Detection, detect, direction_of, endonym_of, isolate
from cairn.messages import text as message
from cairn.query import split_intents
from cairn.retrieve import Candidate, RetrievalTrace, retrieve
from cairn.tabular import (
    Table,
    TableQuery,
    parse_count_query,
    render_row,
    run_count,
)

# A bound count that ran: the tool call as issued, the table it bound, and the
# matching row numbers in file order.
_BoundCount = tuple[TableQuery, Table, list[int]]


class EngineError(ValueError):
    """The request cannot be served as asked (e.g. an unknown language)."""


@dataclass(frozen=True)
class Attempt:
    """One pass of retrieval, and the scope it searched."""

    scope: str  # "language" (restricted) or "corpus" (widened fallback)
    trace: RetrievalTrace

    @property
    def jurisdiction(self) -> str | None:
        """The layer this pass searched, read off the trace rather than
        stored again. Two copies of one fact is one fact that can disagree
        with itself, and this one decides what a disclosure says."""
        return self.trace.jurisdiction

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "lang": self.trace.lang,
            "jurisdiction": self.trace.jurisdiction,
            "excluded": self.trace.excluded,
            "unlabelled": self.trace.unlabelled,
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
    tool: dict[str, Any] | None = None
    # The jurisdiction the question was asked about, after the explicit
    # request and the configured default have been resolved. `None` means no
    # layer was in force, which is every corpus that does not use the field.
    jurisdiction: str | None = None

    @property
    def lang(self) -> str:
        return self.answer.lang

    @property
    def cross_language(self) -> bool:
        return any(source.lang != self.answer.lang for source in self.answer.sources)

    @property
    def cross_jurisdiction(self) -> bool:
        """True when something quoted comes from a layer other than the one
        asked about — the condition a notice must always accompany.

        Derived from the sources actually cited, not from which attempt won,
        for the same reason `cross_language` is: "the widened pass won" is a
        proxy for "the source is from another layer", and a proxy is a thing
        that can stop being true without anything failing.
        """
        if self.jurisdiction is None:
            return False
        return any(
            source_jurisdiction != self.jurisdiction
            for source_jurisdiction in self.source_jurisdictions
        )

    @property
    def source_jurisdictions(self) -> tuple[str | None, ...]:
        """The layer each quoted passage came from, in citation order.

        Read off the winning trace's accepted candidates rather than off
        `Answer.sources`, because a `Source` carries the language it needs for
        layout and nothing about jurisdiction; adding a field there would put
        a layer code on every rendered citation for the benefit of one
        property.
        """
        used = self.answer.trace.accepted[: len(self.answer.sources)]
        return tuple(c.passage.jurisdiction for c in used)


def available_languages(index: Index) -> tuple[str, ...]:
    """Languages that may be asked for: every interface language, plus any
    corpus language that has no interface strings of its own. An interface
    language with no corpus behind it is still answerable — it refuses, or
    cites another language's sources, in the right words."""
    return tuple(sorted(set(LANGUAGES) | set(index.language_codes)))


def _tables_in(index: Index, lang: str) -> tuple[Table, ...]:
    """The corpus tables written in ``lang``, in index order."""
    return tuple(table for table in index.tables if table.lang == lang)


def _bind_count(question: str, tables: tuple[Table, ...]) -> _BoundCount | None:
    """Bind and run a count over ``tables``, or ``None`` if it does not.

    One scope, one answer. ``None`` covers both ways this can come to nothing
    — no complete binding, and a bound column the arithmetic will not read —
    because the caller does the same thing with either: try a wider scope if
    it is allowed one, and otherwise let passage retrieval have the question.
    """
    query = parse_count_query(question, tables)
    if query is None:
        return None
    executed = run_count(query, tables)
    if executed is None:
        return None
    table, matched = executed
    return query, table, matched


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
    # The same order the module docstring states for retrieval, applied to
    # the tables: restrict to the answer language first, and widen to the
    # whole corpus only if nothing bound there and configuration allows it.
    # This path used to skip both halves, so a Spanish question bound an
    # English-only table with no widening step to disclose and no switch to
    # consult — `cross_language_fallback = false` was documented as the way
    # to force a refusal and had no effect here at all.
    bound = _bind_count(question, _tables_in(index, response_lang))
    if bound is None and cfg.cross_language_fallback:
        bound = _bind_count(question, index.tables)
    if bound is None:
        return None
    query, table, matched = bound
    rtl = direction_of(response_lang) == "rtl"
    contact = cfg.contact_for(response_lang)
    refusal_text = message(
        "refusal", response_lang, contact=isolate(contact) if rtl else contact
    )
    # `attempted=False` is load-bearing, not decoration. Retrieval genuinely
    # did not run here, and without this flag the placeholder below is
    # byte-identical to the trace a real search produces when a language has
    # no passages at all -- so `explain`, `refusal_reason` and `calibrate`
    # each read "scoring found nothing" off a trace that was never scored.
    trace = RetrievalTrace(
        query=question, threshold=cfg.threshold, candidates=(), attempted=False
    )
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
        # Every row quoted here comes from the one bound table, so the
        # crossing is one language. How many sources it covers is not fixed:
        # `matched` is one Source per row. The singular wording says "the only
        # source I have for this", which two quoted rows make false, and
        # `messages.py` refuses that reuse in as many words. Same rule the
        # passage path applies at `len(used) == 1`, same reason.
        key = (
            "cross_language_notice"
            if len(matched) == 1
            else "cross_language_notice_partial"
        )
        notice += " " + message(
            key, response_lang, language=isolate(endonym_of(table.lang), rtl=rtl)
        )
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


def resolve_jurisdiction(
    index: Index, cfg: Config, requested: str | None
) -> str | None:
    """The layer a question is about: the explicit request, else the config.

    Refuses rather than falls back, in both directions this can be wrong.

    A malformed code is refused because it would restrict retrieval to a
    label no document can carry, and "no source covers that" is what an
    unanswerable question and a typed flag would then look like alike.

    A well-formed code against a corpus carrying no jurisdictions at all is
    also refused, and that is the less obvious half. Ignoring it would answer
    the question from unlabelled pages and present the result as the layer
    that was asked for — a request silently not honoured, which is this
    project's dominant defect class wearing a config key. A *specific* layer
    with no pages of its own is a different thing entirely and is not refused:
    a county whose own material is not published yet is the ordinary case, and
    it answers from the state layer under a notice.
    """
    code = requested if requested is not None else cfg.default_jurisdiction
    if code is None:
        return None
    if not JURISDICTION_CODE.match(code):
        raise EngineError(
            f"{code!r} is not a jurisdiction code. Expected lowercase "
            f"alphanumeric segments joined by single hyphens, outermost first "
            f"— 'us', 'us-ca', 'us-ca-sonoma'."
        )
    if not index.jurisdiction_codes:
        raise EngineError(
            f"asked about jurisdiction {code!r}, but no document in this corpus "
            f"declares one. Answering anyway would present pages that say "
            f"nothing about where they apply as the rule for {code}. Add "
            f"`jurisdiction:` to the corpus front matter, or ask without a "
            f"jurisdiction."
        )
    return code


def _retrieve_scoped(
    question: str, index: Index, cfg: Config, *, lang: str | None, jurisdiction: str | None
) -> RetrievalTrace:
    """One retrieval pass at one scope, through whichever pass is configured."""
    if cfg.split_intents:
        return split_intents(
            question,
            index,
            threshold=cfg.threshold,
            candidates=cfg.candidates,
            lang=lang,
            jurisdiction=jurisdiction,
            dense_weight=cfg.dense_weight,
        )
    return retrieve(
        question,
        index,
        threshold=cfg.threshold,
        candidates=cfg.candidates,
        lang=lang,
        jurisdiction=jurisdiction,
        dense_weight=cfg.dense_weight,
    )


def _search(
    question: str,
    index: Index,
    cfg: Config,
    *,
    response_lang: str,
    jurisdiction: str | None,
) -> tuple[list[Attempt], RetrievalTrace]:
    """Every retrieval pass made, and the trace the answer is composed from.

    Jurisdiction outermost, one layer at a time from the most specific, and
    the first layer that grounds wins. Language is the inner axis and behaves
    exactly as it always has within each layer.

    When nothing grounds anywhere the *first* attempt is the one returned,
    not the last. That is the pass the person actually asked for — their
    language, their layer — and it is what `explain` diagnoses and what
    `refusal_reason` counts. Returning the widest, most permissive pass
    instead would report every refusal as a failure of a search nobody
    requested.
    """
    attempts: list[Attempt] = []
    for rung in ladder(jurisdiction):
        primary = _retrieve_scoped(
            question, index, cfg, lang=response_lang, jurisdiction=rung
        )
        attempts.append(Attempt(scope="language", trace=primary))
        if primary.grounded:
            return attempts, primary
        if cfg.cross_language_fallback:
            widened = retrieve(
                question,
                index,
                threshold=cfg.threshold,
                candidates=cfg.candidates,
                lang=None,
                jurisdiction=rung,
                dense_weight=cfg.dense_weight,
            )
            attempts.append(Attempt(scope="corpus", trace=widened))
            if widened.grounded:
                return attempts, widened
        if not cfg.cross_jurisdiction_fallback:
            break
    return attempts, attempts[0].trace


def _language_notice(
    used: tuple[Candidate, ...], response_lang: str, *, rtl: bool
) -> str | None:
    """The cross-language disclosure for the passages actually quoted."""
    foreign: list[str] = []
    for candidate in used:
        if candidate.passage.lang != response_lang and candidate.passage.lang not in foreign:
            foreign.append(candidate.passage.lang)
    if not foreign:
        return None
    # Singular only when there is genuinely one source and it is foreign.
    key = "cross_language_notice" if len(used) == 1 else "cross_language_notice_partial"
    return message(
        key,
        response_lang,
        language=", ".join(isolate(endonym_of(code), rtl=rtl) for code in foreign),
    )


def _jurisdiction_notice(
    used: tuple[Candidate, ...], response_lang: str, asked: str | None
) -> str | None:
    """The cross-jurisdiction disclosure for the passages actually quoted.

    Keyed on the layers of the quoted passages, not on which attempt won, for
    the reason set out at length beside the cross-language notice: "a wider
    pass won" is a proxy, and this sentence has to be true of the text
    underneath it.

    There is no ``_partial`` variant here, and its absence is deliberate
    rather than an omission. The cross-language notice needs one because a
    single retrieval pass can return passages in several languages at once, so
    "the only source" can be false of the text below it. A jurisdiction pass
    searches exactly one layer (see :func:`_search`), so every passage it can
    return carries the same code and the mixed case does not arise. A second
    key would be a sentence nothing could ever make Cairn say, and the
    disclosure suite would have to be handed a scenario that does not exist.
    The wording is written so that it stays true of one quoted passage or
    several.
    """
    if asked is None:
        return None
    wider = sorted(
        {
            c.passage.jurisdiction
            for c in used
            if c.passage.jurisdiction is not None and c.passage.jurisdiction != asked
        }
    )
    if not wider:
        return None
    return message(
        "cross_jurisdiction_notice",
        response_lang,
        jurisdiction=", ".join(wider),
        asked=asked,
    )


def ask(
    question: str,
    index: Index,
    cfg: Config,
    *,
    lang: str | None = None,
    jurisdiction: str | None = None,
) -> AskResult:
    languages = available_languages(index)
    if lang is not None and lang not in languages:
        raise EngineError(
            f"unsupported language {lang!r}; this corpus and interface offer: "
            + ", ".join(languages)
        )
    asked_jurisdiction = resolve_jurisdiction(index, cfg, jurisdiction)

    detection = detect(question, index, default=cfg.default_lang, requested=lang)
    response_lang = detection.lang
    rtl = direction_of(response_lang) == "rtl"

    # The count tool is skipped entirely while a jurisdiction is in force;
    # see this module's docstring for why an unlabelled table may not answer
    # a question asked about a particular place.
    if cfg.tables_enabled and index.tables and asked_jurisdiction is None:
        table_result = _answer_from_tables(
            question, index, cfg, response_lang=response_lang, detection=detection
        )
        if table_result is not None:
            return table_result

    attempts, chosen = _search(
        question,
        index,
        cfg,
        response_lang=response_lang,
        jurisdiction=asked_jurisdiction,
    )

    # Both notices describe the passages that are actually quoted, which is
    # the slice composition will take — not the widening that went looking
    # for them. Two things were wrong with keying the language one on
    # `chosen is not primary`, and both apply to the jurisdiction one too.
    #
    # It was a proxy: "the widened pass won" happens to imply "the source is
    # in another language" only because a passage scores identically in both
    # passes, so a widened pass can never surface a response-language passage
    # the restricted pass did not already have. Nothing states that and
    # nothing tests it, and it stops being true the moment IDF becomes
    # scope-relative.
    #
    # And it read one passage's language while `compose` quotes
    # `max_passages` of them. At `max_passages = 2` an Arabic questioner could
    # be handed a Spanish passage and an English one under a notice naming
    # Spanish alone and calling it "the only source" — two false statements in
    # a sentence whose entire job is to say what language the answer is in.
    used = chosen.accepted[:cfg.max_passages]
    # Jurisdiction first: which place's rule this is comes before which
    # language it is written in, because a reader who stops after one
    # sentence has to be told the more consequential thing.
    notice = " ".join(
        part
        for part in (
            _jurisdiction_notice(used, response_lang, asked_jurisdiction),
            _language_notice(used, response_lang, rtl=rtl),
        )
        if part
    ) or None

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
    return AskResult(
        answer=answer,
        detection=detection,
        attempts=tuple(attempts),
        jurisdiction=asked_jurisdiction,
    )
