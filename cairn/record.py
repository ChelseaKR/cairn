"""Recording the evidence the auditor grades.

`cairn record` runs the real engine over a committed set of questions and
writes an evidence bundle: what was asked, what came back, what sources were
available, and a snapshot of the interface it would have been asked in. The
auditor (see `plumbline.pin`) then grades that bundle.

Three properties this module exists to hold:

**The evidence is produced, never edited.** Responses come from
``engine.ask``, the same call the CLI and the web interface make. There is no
hand-written expected-output file that could quietly diverge from what the
engine does. Re-running with an unchanged corpus and configuration writes
byte-identical files, so a diff in the bundle means a change in behavior.

**Cairn does not need the auditor to produce its own evidence.** The bundle
format is published and versioned, so the recorder writes it directly —
checksums included. The engine's install, lint and test path never touches the
harness; the harness's job is to verify, and if Cairn computed a checksum
wrongly the audit refuses to score rather than passing quietly.

**The questions are authored; everything else is measured.** ``questions.toml``
holds what a person decided to ask, what a correct answer would say, and which
passage answers it — that last one is ground truth only a reader of the corpus
can supply, and it is what lets the audit tell "the right document" from "the
right paragraph of it". Which passages were retrieved, what the system
replied, and what the interface looks like are all recorded from the running
system.

An item's recorded ``sources`` are every passage retrieval **accepted**, not
only the ones composition quoted. Those are the passages the answer could have
been built from, which is what makes "it was built from the wrong one" a
question with an answer; recording only the quoted passage makes every item
trivially attributed to the one thing it had.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.answer import citation_marker
from cairn.config import Config
from cairn.engine import ask
from cairn.index import Index
from cairn.ui.contrast import declarations
from cairn.ui.page import render_page

BUNDLE_FORMAT = "plumbline-bundle"
CHECKSUMS_FORMAT = "plumbline-checksums"
FORMAT_VERSION = 1

CONTRAST_ELEMENT_ID = "plumbline-contrast"

# Cairn names a passage `<doc-id>#<ordinal>`. The bundle format's inline
# citation grammar has no "#" in it, so a citation to `grocery-allowance-en#2`
# would not be recognized as a citation at all — and worse, the ordinal would
# leak into the numbers a cross-language check compares. The separator becomes
# a dot for interchange only; the mapping is one character and stated in the
# bundle's own DATASET.md so a reader can go from an audit finding back to a
# passage. Cairn's own identifiers are untouched.
#
# The mapping itself lives in `cairn.answer` with the answer it marks up,
# because the served interface has to be able to produce the same string:
# see `Answer.cited_text`.
source_id = citation_marker

DEFAULT_QUESTIONS = "plumbline/questions.toml"
DEFAULT_BUNDLE = "plumbline/bundle"

# Fields copied straight from the authored question to the recorded item.
AUTHORED_FIELDS = (
    "lang",
    "behavior",
    "group",
    "prompt",
    "expected",
    "load_bearing",
    "fact_id",
    "adversarial",
    "forbidden",
    "translation",
    # Which passage answers the question. Authored ground truth, and the only
    # thing that lets the audit distinguish "answered from the right document"
    # from "answered from the right paragraph of it".
    "answering_sources",
    # The two opt-in declarations the pinned harness gained on 2026-09-07, and
    # the reason both are authored here rather than observed from the answer.
    #
    # `expected_response_lang` says an answer is *supposed* to come back in a
    # language other than the one the question was written in, and why. Only a
    # person who has read the corpus can say that: `multilingual` scores the
    # declaration instead of the question's own tag, so a recorder that wrote
    # one from what the engine happened to reply would be letting the target
    # set its own target.
    #
    # `target_voice` names literal strings the answer emits in Cairn's own
    # voice — a cross-language notice, the count tool's preamble — which
    # `groundedness`, `citation_accuracy` and `passage_attribution` remove
    # before measuring what the sources support. That one is *more* dangerous
    # to observe: deriving it from `Answer.notice` would mean the engine could
    # exempt any sentence from a support measure by putting it in the notice,
    # which is the pass-buying move the harness's own ADR 0005 names. So it is
    # authored, and `target_voice_drift` below holds the authored string to the
    # recorded response rather than trusting either end.
    "expected_response_lang",
    "target_voice",
)


# Everything `expected_response_lang` may say, and the harness refuses the
# bundle over any other spelling. Checked here so the refusal arrives while a
# person is still editing the question set, rather than one command later
# against a bundle already written to disk.
EXPECTED_RESPONSE_LANG_KEYS = ("lang", "reason")


class RecordError(ValueError):
    """The question set is malformed, or the bundle cannot be written."""


def _check_expected_response_lang(file: Path, question: dict[str, Any]) -> None:
    """The cross-language declaration: an object, both keys, neither blank,
    and not the language the question was already asked in.

    Every rule here is the pinned harness's, restated rather than imported —
    the recorder does not depend on the auditor, which is the whole point of
    writing the bundle format directly. The reason to restate them is that the
    harness refuses a *written* bundle, and a question set that cannot be
    recorded should say so before it is recorded.
    """
    declared = question.get("expected_response_lang")
    if declared is None:
        return
    if not isinstance(declared, dict):
        raise RecordError(
            f"{file}: item {question['id']} sets expected_response_lang to "
            f"something that is not a table; it takes a lang and a reason."
        )
    unknown = sorted(set(declared) - set(EXPECTED_RESPONSE_LANG_KEYS))
    if unknown:
        raise RecordError(
            f"{file}: item {question['id']} sets expected_response_lang keys "
            f"nothing reads: {', '.join(unknown)}."
        )
    for key in EXPECTED_RESPONSE_LANG_KEYS:
        value = declared.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RecordError(
                f"{file}: item {question['id']} declares an "
                f"expected_response_lang with no {key}. A declaration that "
                f"moves what a suite measures against is published in the "
                f"audit report, and a reader has to be able to weigh it."
            )
    if declared["lang"] == question["lang"]:
        raise RecordError(
            f"{file}: item {question['id']} declares expected_response_lang "
            f"{declared['lang']!r}, which is the language it was asked in. "
            f"That declares nothing and reads like a reviewed decision about "
            f"a cross-language answer. Remove it."
        )


def _check_target_voice_declaration(file: Path, question: dict[str, Any]) -> None:
    """`target_voice` is a list of literal, non-blank strings."""
    declared = question.get("target_voice")
    if declared is None:
        return
    if not isinstance(declared, list) or not all(
        isinstance(s, str) for s in declared
    ):
        raise RecordError(
            f"{file}: item {question['id']} sets target_voice to something "
            f"other than a list of literal strings the answer emits in "
            f"Cairn's own voice."
        )
    if any(not s.strip() for s in declared):
        raise RecordError(
            f"{file}: item {question['id']} declares an empty target_voice "
            f"string. Excluding nothing is not an exclusion."
        )


@dataclass(frozen=True)
class BundleReport:
    path: str
    item_count: int
    answer_count: int
    refusal_count: int
    languages: tuple[str, ...]
    bundle_sha256: str


def load_questions(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        raise RecordError(f"no question set at {file}")
    with open(file, "rb") as handle:
        data = tomllib.load(handle)
    questions: list[dict[str, Any]] = data.get("item", [])
    if not questions:
        raise RecordError(f"{file}: no [[item]] entries")
    seen: set[str] = set()
    for question in questions:
        for required in ("id", "lang", "behavior", "prompt"):
            if not question.get(required):
                raise RecordError(f"{file}: an item is missing {required!r}")
        if question["behavior"] not in ("answer", "refuse"):
            raise RecordError(
                f"{file}: item {question['id']} has behavior "
                f"{question['behavior']!r}; expected 'answer' or 'refuse'"
            )
        if question["id"] in seen:
            raise RecordError(f"{file}: duplicate item id {question['id']!r}")
        seen.add(question["id"])
        declared = question.get("answering_sources")
        if question["behavior"] == "answer" and not declared:
            raise RecordError(
                f"{file}: item {question['id']} expects an answer but does not "
                f"declare answering_sources. Only the question set can say "
                f"which passage answers a question, and an item that does not "
                f"say is reported unverifiable — a question set full of those "
                f"is a check that is not running."
            )
        if question["behavior"] == "refuse" and declared:
            raise RecordError(
                f"{file}: item {question['id']} expects a refusal and declares "
                f"answering_sources. Nothing answers a question that should "
                f"not be answered."
            )
        _check_expected_response_lang(file, question)
        _check_target_voice_declaration(file, question)
    return questions


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _json(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def interface_snapshot(page: str | None = None) -> str:
    """The real page, plus the colour pairs it uses, for an auditor to check.

    The declaration is generated from the stylesheet's own custom properties,
    in both presentations. It is not served to anyone: adding an auditor's
    data block to the live page would be scaffolding shipped to users, and the
    thing being audited should be the thing that ships.

    ``page`` is the markup to wrap, and defaults to rendering it in process.
    The live check passes the bytes it fetched from the running server, so
    that "is the audited snapshot the page that is actually served?" is one
    byte comparison against a snapshot built the same way, rather than a
    second, drifting idea of what the wrapping looks like.
    """
    palette = declarations("light") + declarations("dark")
    block = (
        f'  <script type="application/json" id="{CONTRAST_ELEMENT_ID}">\n'
        + json.dumps(palette, ensure_ascii=False, indent=2)
        + "\n  </script>\n"
    )
    note = (
        "<!--\n"
        "  Snapshot of the interface `cairn serve` renders, captured by\n"
        "  `cairn record`. The colour block below is generated from the\n"
        "  stylesheet's own custom properties, in both the light and the dark\n"
        "  presentation, so an auditor computes the contrast ratios rather\n"
        "  than being told they pass. It is hashed with the rest of the\n"
        "  evidence: the interface that was audited is pinned as firmly as\n"
        "  the answers were.\n"
        "-->\n"
    )
    page = render_page("en") if page is None else page
    return note + page.replace("</head>", block + "</head>", 1)


def dataset_page(report_rows: list[dict[str, Any]], name: str) -> str:
    """The bundle's own description, with its counts filled in from the
    bundle rather than typed by hand and left to rot."""
    langs = sorted({row["lang"] for row in report_rows})
    counts = {lang: sum(1 for r in report_rows if r["lang"] == lang) for lang in langs}
    answers = sum(1 for r in report_rows if r["behavior"] == "answer")
    refusals = sum(1 for r in report_rows if r["behavior"] == "refuse")
    adversarial = sum(1 for r in report_rows if r.get("adversarial"))
    unreviewed = sum(
        1
        for r in report_rows
        if (r.get("translation") or {}).get("review") == "unreviewed"
    )
    # Counted separately because they are different claims. "No translation is
    # reviewed" says nothing at all about an item authored directly in Arabic,
    # and reading the first count as the second would let an unreviewed
    # non-English string into the bundle wearing the reassurance owed to a
    # different set of items.
    non_english = sum(1 for r in report_rows if r["lang"] != "en")
    per_language = ", ".join(f"{counts[lang]} {lang}" for lang in langs)
    return f"""# {name}

**Synthetic evidence, recorded from a running system.** The questions were
written by hand; every response was produced by `cairn record` calling the
engine, and every source passage is from the bundled synthetic demo corpus —
an invented county, invented programs, invented amounts. It demonstrates that
the instrument and the target work together. It measures nothing about any
real benefit program.

- {len(report_rows)} items ({per_language}).
- {answers} expected answers, {refusals} expected refusals, {adversarial} of
  them adversarial probes.
- {non_english} items are not in English. {unreviewed} of them are
  translations of an English item and carry `"review": "unreviewed"`, which
  every run says out loud; the remaining {non_english - unreviewed} were
  authored directly in their own language. No non-English string in this
  bundle — translated or authored — has been reviewed by a subject-matter
  expert, and claiming otherwise in an audit record would be the exact
  dishonesty that field exists to prevent.

## How to regenerate

```sh
python3 -m cairn index
python3 -m cairn record
```

Re-recording an unchanged corpus and configuration produces byte-identical
files. A diff here is a change in behavior, and the bundle hash moving is the
trace that says so.

## What is in it

| File | What it is |
| --- | --- |
| `items.jsonl` | The authored questions — including which passage answers |
| | each one — plus every passage retrieval accepted for it |
| `responses.jsonl` | What the engine replied, with the sources it cited |
| | marked inline |
| `sources.jsonl` | Every passage in the corpus, so a citation to something |
| | that does not exist is detectable |
| `interface.html` | A snapshot of the served page, with its colour pairs |
| | declared so they can be checked rather than believed |
| `checksums.json` | SHA-256 per file, and for the bundle |

Source ids here are Cairn passage ids with the `#` before the ordinal written
as a `.`, because the bundle format's inline citation grammar has no `#` in
it. `grocery-allowance-en.2` is `grocery-allowance-en#2`; nothing else about
the identifier changes, so an audit finding maps straight back to a passage.
"""


def bundle_checksums(bundle_dir: Path) -> dict[str, Any]:
    """Checksums in the published bundle format.

    Written here rather than by the harness so that producing evidence never
    requires the thing that audits it. If this were wrong, the audit would
    refuse to score — loudly, with its own exit code — which is why writing it
    on this side is safe.
    """
    digests = {}
    for path in sorted(bundle_dir.iterdir()):
        if not path.is_file() or path.name == "checksums.json":
            continue
        digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    combined = "".join(f"{name}={digest}\n" for name, digest in sorted(digests.items()))
    return {
        "format": CHECKSUMS_FORMAT,
        "format_version": FORMAT_VERSION,
        "algorithm": "sha256",
        "files": digests,
        "bundle_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
    }


def _answering_layer(result: Any) -> str | None:
    """The jurisdiction every quoted source came from, or `None`.

    `None` covers three genuinely different things — a refusal, a corpus
    with no jurisdiction labels, and an answer quoted from an unlabelled
    document — and they are collapsed on purpose, because the caller does
    the same thing with all three: write no group rather than write one that
    is not a jurisdiction. Writing `"none"` or `""` would put a label in the
    disaggregation that is not a layer, and the sweep would report a rate
    for it beside the real ones.

    A composed answer's sources always share one layer (a jurisdiction pass
    searches exactly one; see `cairn.engine._search`), so the set below is a
    guard rather than an expectation: if it ever holds two, nothing is
    written, because there is no single layer to name.
    """
    layers = {code for code in result.source_jurisdictions if code is not None}
    return layers.pop() if len(layers) == 1 else None


def target_voice_drift(question: dict[str, Any], response: str) -> str | None:
    """Why this item's `target_voice` no longer describes its answer, or None.

    The check the pinned harness cannot make, and the reason the declaration
    is safe to author. Removal upstream is literal: a declared string that no
    longer appears removes nothing and is silently a no-op, so the day
    somebody rewords `table_count_notice` in `cairn/messages.py` the exemption
    stops applying and `groundedness` falls for a reason no report names. And
    an over-broad declaration — a string that happens to span a quoted cell —
    would hide part of the answer from the support measure, which is the
    pass-buying move in the other direction.

    Both are recording errors rather than audit findings, so `record()` refuses
    to write a bundle holding one. It is a *reason* rather than a raise because
    the dry-run preview (`cairn.record_diff`) has to be able to show exactly
    this: "the change you are previewing takes the declared notice out of the
    answer" is the most useful thing a preview could say about it, and a
    preview that crashed instead would leave the only way to see it being to
    write the bundle.

    The second half of the check is the harness's own trap: a response that is
    *nothing but* its notice measures, after removal, as the empty string, and
    support for an empty string is arithmetically total.
    """
    declared = question.get("target_voice") or []
    if not declared:
        return None
    for notice in declared:
        if notice not in response:
            return (
                f"declares target_voice text that is not in the answer: "
                f"{notice!r}. The auditor removes these literally, so a "
                f"declaration that matches nothing removes nothing and says "
                f"so to no one."
            )
    remaining = response
    for notice in declared:
        remaining = remaining.replace(notice, " ")
    if not remaining.strip():
        return (
            "declares every word of its own answer as target_voice, so "
            "nothing is left to measure support against. An answer that is "
            "only a notice is not an answer."
        )
    return None


def build_items_and_responses(
    index: Index,
    cfg: Config,
    questions: list[dict[str, Any]],
    *,
    jurisdiction: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The evidence-shaped records :func:`record` writes to `items.jsonl` and
    `responses.jsonl`, built but not written anywhere.

    Factored out so a dry-run preview (`cairn.record_diff`) can compute
    exactly what `record()` would produce without a second implementation of
    what an answer is — the one thing this project is emphatic must never
    exist for anything evidence-shaped.
    """
    items: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    for question in questions:
        result = ask(
            question["prompt"], index, cfg, lang=question["lang"],
            jurisdiction=jurisdiction,
        )
        answer = result.answer
        item = {"id": question["id"]}
        for field in AUTHORED_FIELDS:
            if question.get(field) not in (None, [], {}):
                item[field] = question[field]
        # The layer that answered, so the pinned harness can disaggregate by
        # it — "the county pages answer 8 of 10, the state pages the rest" is
        # the pilot's decision gate, and until now it was reconstructed after
        # the fact from `layers.json` rather than recorded from the engine's
        # own decision.
        #
        # An authored `group` always wins. The question set is ground truth
        # about the question and this is an observation about the answer; a
        # recorder that overwrote the author would silently retitle whatever
        # grouping the set was built around.
        if "group" not in item:
            layer = _answering_layer(result)
            if layer is not None:
                item["group"] = layer
        # "Source ids retrieved for this item" — the passages composition
        # chose from on the retrieval path, or the table rows the tool quoted
        # when a structured tool produced the answer. A tool answer records
        # no retrieval candidates (none ran), and leaving `sources` empty
        # would make its citations unresolvable in the bundle's own index.
        if result.tool is not None:
            item["sources"] = [
                source_id(sid) for sid in result.tool.get("matched_rows", [])
            ]
        else:
            item["sources"] = [
                source_id(candidate.passage.passage_id)
                for candidate in answer.trace.accepted
            ]
        items.append(item)
        responses.append({"id": question["id"], "response": answer.cited_text})
    return items, responses


def record(
    index: Index,
    cfg: Config,
    *,
    questions_path: str | Path = DEFAULT_QUESTIONS,
    out_dir: str | Path = DEFAULT_BUNDLE,
    name: str = "cairn-demo",
    jurisdiction: str | None = None,
) -> BundleReport:
    questions = load_questions(questions_path)
    bundle = Path(out_dir)
    bundle.mkdir(parents=True, exist_ok=True)

    items, responses = build_items_and_responses(
        index, cfg, questions, jurisdiction=jurisdiction
    )
    # Refused here rather than inside the builder, so `cairn record --dry-run`
    # can report the same drift as a previewed difference instead of crashing
    # on it. Nothing is written until every declaration still describes the
    # answer it was written about.
    by_id = {response["id"]: response["response"] for response in responses}
    for question in questions:
        reason = target_voice_drift(question, by_id[question["id"]])
        if reason is not None:
            raise RecordError(
                f"{questions_path}: item {question['id']} {reason} Re-read the "
                f"answer this question now produces and write what it says."
            )

    sources = [
        {
            "id": source_id(passage.passage_id),
            "title": passage.title,
            "text": passage.text,
        }
        for passage in index.passages
    ]
    # Table rows join the bundle's resolvable-source universe: a citation to
    # `<table-id>.<row>` must resolve exactly like one to a passage.
    from cairn.tabular import render_row

    sources.extend(
        {
            "id": source_id(f"{table.table_id}#{number}"),
            "title": f"{table.title} (row {number})",
            "text": render_row(table, number),
        }
        for table in index.tables
        for number in range(1, table.row_count + 1)
    )

    _jsonl(bundle / "items.jsonl", items)
    _jsonl(bundle / "responses.jsonl", responses)
    _jsonl(bundle / "sources.jsonl", sources)
    (bundle / "interface.html").write_text(
        interface_snapshot(), encoding="utf-8", newline="\n"
    )
    (bundle / "DATASET.md").write_text(
        dataset_page(items, name), encoding="utf-8", newline="\n"
    )
    _json(
        bundle / "manifest.json",
        {
            "format": BUNDLE_FORMAT,
            "format_version": FORMAT_VERSION,
            "name": name,
            "version": "1.0.0",
            "synthetic": True,
            "description": (
                "Evidence recorded from Cairn answering a committed set of "
                "questions against its bundled synthetic demo corpus. The "
                "questions are authored; every response was produced by the "
                "engine. Demonstrates the target and the instrument working "
                "together; not a benchmark."
            ),
            "files": {
                "items": "items.jsonl",
                "responses": "responses.jsonl",
                "sources": "sources.jsonl",
                "interface": "interface.html",
            },
        },
    )
    checksums = bundle_checksums(bundle)
    _json(bundle / "checksums.json", checksums)

    return BundleReport(
        path=str(bundle),
        item_count=len(items),
        answer_count=sum(1 for i in items if i["behavior"] == "answer"),
        refusal_count=sum(1 for i in items if i["behavior"] == "refuse"),
        languages=tuple(sorted({i["lang"] for i in items})),
        bundle_sha256=checksums["bundle_sha256"],
    )
