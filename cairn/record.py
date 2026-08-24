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
)


class RecordError(ValueError):
    """The question set is malformed, or the bundle cannot be written."""


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
    raw_questions = data.get("item", [])
    if not raw_questions or not isinstance(raw_questions, list):
        raise RecordError(f"{file}: no [[item]] entries")
    questions: list[dict[str, Any]] = [dict(q) for q in raw_questions]
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


def build_items_and_responses(
    index: Index, cfg: Config, questions: list[dict[str, Any]]
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
        result = ask(question["prompt"], index, cfg, lang=question["lang"])
        answer = result.answer
        item = {"id": question["id"]}
        for field in AUTHORED_FIELDS:
            if question.get(field) not in (None, [], {}):
                item[field] = question[field]
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
) -> BundleReport:
    questions = load_questions(questions_path)
    bundle = Path(out_dir)
    bundle.mkdir(parents=True, exist_ok=True)

    items, responses = build_items_and_responses(index, cfg, questions)

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
