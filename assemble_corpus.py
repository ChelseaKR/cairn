"""Assemble a layered corpus into the one flat directory `cairn index` reads.

Dev-only, stdlib-only, never part of the runtime. `[corpus] path` in
`cairn.toml` names exactly one directory, and `cairn index` reads the `*.md`
files directly in it plus `tables/*.csv`. That is the right shape for an
operator with one corpus. The real-corpus pilot (`docs/pilot-ca.md`) has a
corpus in three layers — federal, California, and one county — because a
county agency's deployment is federal pages plus state pages plus its own,
and the federal and state layers are the same bytes for every county. Held
as one directory per county, a correction to a federal page would have to be
made three times; held as layers, it is made once and assembled.

So this script copies layers into a flat directory, writes a `cairn.toml`
beside it from a template, and refuses a few things on the way:

- a document still carrying `import_corpus.py`'s `review: unreviewed`
  marker, unless `--allow-unreviewed` is given — a scaffold nobody has
  read is not a corpus document, and assembling it would make it one;
- two layers declaring the same document id — a citation to it would
  resolve to whichever file was copied last;
- a county the pilot's `pilot.toml` does not declare — every assembled
  corpus has a real `[refusal] contact`, and that contact is the county's.

The layers are declared in `<pilot>/pilot.toml`::

    [layers]
    shared = ["federal", "california"]

    [counties.los-angeles]
    name = "Los Angeles County"
    contact = "the Los Angeles County DPSS Customer Service Center at ..."

    [counties.fresno]
    ...

and each layer is `<pilot>/layers/<layer>/*.md` with an optional
`tables/*.csv` under it. `--county NAME` assembles the shared layers plus
that county's; `--combined` assembles the shared layers plus *every*
county's, which is not a deployable corpus and is not meant to be: it is
the arm of the pilot that measures what happens when a question with
fifty-eight correct answers is asked of a corpus holding three of them.

The assembled directory is derived output — `.gitignore`d, rebuilt by
re-running — and the index built from it is fingerprinted over the
assembled files exactly as for any corpus, so a stale assembly is a stale
index, caught the same way.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cairn.corpus import CorpusError, load_document
from cairn.tabular import TABLES_DIRNAME, load_table

PILOT_FILE = "pilot.toml"
LAYERS_DIRNAME = "layers"
TEMPLATE_NAME = "cairn.template.toml"
LAYERS_FILE = "layers.json"
UNREVIEWED_MARKER = "unreviewed"


class AssembleError(ValueError):
    """Nothing is written when this is raised."""


@dataclass(frozen=True)
class County:
    key: str
    name: str
    contact: str


@dataclass(frozen=True)
class Pilot:
    root: Path
    shared: tuple[str, ...]
    counties: dict[str, County]

    def layer_dir(self, layer: str) -> Path:
        return self.root / LAYERS_DIRNAME / layer


def load_pilot(root: str | Path) -> Pilot:
    base = Path(root)
    path = base / PILOT_FILE
    if not path.is_file():
        raise AssembleError(f"no {PILOT_FILE} in {base}")
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    shared = tuple(data.get("layers", {}).get("shared", []))
    if not shared:
        raise AssembleError(f"{path}: [layers] shared is empty")
    counties: dict[str, County] = {}
    for key, entry in data.get("counties", {}).items():
        name, contact = entry.get("name"), entry.get("contact")
        if not name or not contact:
            raise AssembleError(
                f"{path}: county {key!r} needs both 'name' and 'contact' — an assembled "
                f"corpus refuses to a real person, and that person is the county's"
            )
        counties[key] = County(key=key, name=name, contact=contact)
    if not counties:
        raise AssembleError(f"{path}: no [counties.*] declared")
    for layer in shared:
        if not (base / LAYERS_DIRNAME / layer).is_dir():
            raise AssembleError(f"{path}: shared layer {layer!r} has no directory in layers/")
    return Pilot(root=base, shared=shared, counties=counties)


def is_unreviewed(path: Path) -> bool:
    """Does the front matter still carry `review: unreviewed`? Read from the
    raw lines rather than `load_document`, which (rightly) never surfaces
    inert keys — this marker is for people and for this script only."""
    with open(path, encoding="utf-8") as handle:
        first = handle.readline().strip()
        if first != "---":
            return False
        for line in handle:
            if line.strip() == "---":
                return False
            key, sep, value = line.partition(":")
            if sep and key.strip() == "review" and value.strip() == UNREVIEWED_MARKER:
                return True
    return False


def _documents(layer_dir: Path) -> list[Path]:
    return sorted(p for p in layer_dir.glob("*.md") if p.name.lower() != "readme.md")


def _tables(layer_dir: Path) -> list[Path]:
    tables = layer_dir / TABLES_DIRNAME
    return sorted(tables.glob("*.csv")) if tables.is_dir() else []


def _plan_documents(
    docs: list[Path],
    ids: dict[str, Path],
    files: list[Path],
    *,
    allow_unreviewed: bool,
) -> list[str]:
    """Validate one layer's `*.md` documents, returning what is wrong with them.

    `ids` and `files` belong to the whole plan rather than to this layer, and
    are handed in for that reason: a duplicate id is a collision *between*
    layers, so the map of who claimed what has to outlive the layer being
    scanned. A document that will not load claims nothing, which is why the
    `continue` comes before either claim.
    """
    problems: list[str] = []
    for path in docs:
        try:
            doc = load_document(path)
        except CorpusError as exc:
            problems.append(str(exc))
            continue
        if not allow_unreviewed and is_unreviewed(path):
            problems.append(
                f"{path}: still marked 'review: unreviewed' — read it, fix the id, "
                f"delete the marker (or pass --allow-unreviewed for a smoke run)"
            )
        if doc.doc_id in ids:
            problems.append(
                f"{path}: document id {doc.doc_id!r} is also declared by {ids[doc.doc_id]}"
            )
        ids[doc.doc_id] = path
        files.append(path)
    return problems


def _plan_tables(tables: list[Path], ids: dict[str, Path], files: list[Path]) -> list[str]:
    """The same for one layer's `tables/*.csv`, against the same shared `ids`.

    Deliberately the same map the documents are claimed into: a citation names
    one id space, not two, so a table id colliding with a document id is the
    same defect as two document ids colliding and reads the same here.
    """
    problems: list[str] = []
    for path in tables:
        try:
            table = load_table(path)
        except CorpusError as exc:
            problems.append(str(exc))
            continue
        if table.table_id in ids:
            problems.append(
                f"{path}: table id {table.table_id!r} is also declared by "
                f"{ids[table.table_id]}"
            )
        ids[table.table_id] = path
        files.append(path)
    return problems


def plan(
    pilot: Pilot,
    layers: tuple[str, ...],
    *,
    allow_unreviewed: bool,
    warn: Callable[[str], None] = lambda _: None,
) -> list[Path]:
    """Every file that would be copied, validated, before anything is written.
    Validation loads each document through the same function `cairn index`
    uses, so a layer file that cannot be indexed fails here with the same
    message rather than after assembly.

    An empty layer is a warning, not an error: while a county's terms
    question is open (docs/pilot-ca.md, Finding 0) its layer directory is
    empty, and the other two layers are still worth assembling — as long as
    the output says a layer was missing, which the `layers.json` it writes
    and the warning here both do."""
    files: list[Path] = []
    ids: dict[str, Path] = {}
    problems: list[str] = []
    for layer in layers:
        layer_dir = pilot.layer_dir(layer)
        if not layer_dir.is_dir():
            problems.append(f"layer {layer!r}: no directory at {layer_dir}")
            continue
        docs = _documents(layer_dir)
        tables = _tables(layer_dir)
        if not docs and not tables:
            warn(f"layer {layer!r} is empty ({layer_dir}); assembling without it")
        problems += _plan_documents(docs, ids, files, allow_unreviewed=allow_unreviewed)
        problems += _plan_tables(tables, ids, files)
    if problems:
        raise AssembleError("\n".join(problems))
    return files


def layer_of(pilot: Pilot, files: list[Path]) -> dict[str, str]:
    """`{doc_or_table_id: layer}` for every planned file, by which layer
    directory it sits in."""
    out: dict[str, str] = {}
    for path in files:
        layer = path.parent.name if path.suffix != ".csv" else path.parent.parent.name
        if path.suffix == ".csv":
            out[load_table(path).table_id] = layer
        else:
            out[load_document(path).doc_id] = layer
    return out


def render_config(template: str, *, corpus_path: str, index_path: str, contact: str) -> str:
    """`{{CORPUS_PATH}}`, `{{INDEX_PATH}}`, `{{CONTACT}}` substituted into the
    pilot's config template. Every placeholder must be present: a template
    that forgot `{{CONTACT}}` would ship the template's own contact line,
    and the point of templating is that the contact is never a default."""
    rendered = template
    for key, value in (
        ("{{CORPUS_PATH}}", corpus_path),
        ("{{INDEX_PATH}}", index_path),
        ("{{CONTACT}}", contact),
    ):
        if key not in rendered:
            raise AssembleError(f"{TEMPLATE_NAME}: missing placeholder {key}")
        rendered = rendered.replace(key, value)
    return rendered


def assemble(
    pilot: Pilot,
    out_dir: Path,
    *,
    county: str | None,
    combined: bool,
    allow_unreviewed: bool = False,
    warn: Callable[[str], None] = lambda _: None,
) -> tuple[int, int]:
    """Copy the planned files into `out_dir` (cleared first) and write its
    `cairn.toml`. Returns `(documents, tables)` copied."""
    if combined == bool(county):
        raise AssembleError("give exactly one of --county NAME or --combined")
    if county and county not in pilot.counties:
        known = ", ".join(sorted(pilot.counties))
        raise AssembleError(f"county {county!r} is not declared in {PILOT_FILE} ({known})")
    county_layers = tuple(sorted(pilot.counties)) if combined else (county,)
    layers = pilot.shared + tuple(c for c in county_layers if c)
    files = plan(pilot, layers, allow_unreviewed=allow_unreviewed, warn=warn)
    provenance = layer_of(pilot, files)

    template_path = pilot.root / TEMPLATE_NAME
    if not template_path.is_file():
        raise AssembleError(f"no {TEMPLATE_NAME} in {pilot.root}")
    if combined:
        contact = (
            "no single office — this combined corpus spans "
            + ", ".join(pilot.counties[c].name for c in county_layers if c)
            + " and is a measurement arm, not a deployment"
        )
    else:
        contact = pilot.counties[county].contact  # type: ignore[index]
    config = render_config(
        template_path.read_text(encoding="utf-8"),
        corpus_path=out_dir.as_posix(),
        index_path=(out_dir / ".cairn" / "index.json").as_posix(),
        contact=contact,
    )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / TABLES_DIRNAME).mkdir(parents=True)
    docs = tables = 0
    for path in files:
        if path.suffix == ".csv":
            shutil.copyfile(path, out_dir / TABLES_DIRNAME / path.name)
            tables += 1
        else:
            shutil.copyfile(path, out_dir / path.name)
            docs += 1
    if not tables:
        (out_dir / TABLES_DIRNAME).rmdir()
    (out_dir / "cairn.toml").write_text(config, encoding="utf-8")
    # Which layer each document came from. Flattening loses it, and the
    # pilot's sweep needs it back to say "answered from the federal page when
    # the county page held the answer" — so it is written down here, the one
    # place that still knows. Inert to `cairn index`, which reads only *.md
    # and tables/*.csv.
    with open(out_dir / LAYERS_FILE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"layers": list(layers), "documents": provenance},
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return docs, tables


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble federal + state + county layers into one corpus directory."
    )
    parser.add_argument("pilot", help=f"pilot directory holding {PILOT_FILE} and layers/")
    parser.add_argument("-o", "--output", required=True, help="directory to assemble into")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--county", help="assemble the shared layers plus this county's")
    group.add_argument(
        "--combined",
        action="store_true",
        help="assemble the shared layers plus every county's (a measurement arm)",
    )
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="include documents still marked 'review: unreviewed' (smoke runs only)",
    )
    args = parser.parse_args(argv)
    try:
        pilot = load_pilot(args.pilot)
        docs, tables = assemble(
            pilot,
            Path(args.output),
            county=args.county,
            combined=args.combined,
            allow_unreviewed=args.allow_unreviewed,
            warn=lambda message: print(f"WARNING: {message}", file=sys.stderr),
        )
    except AssembleError as exc:
        print(f"assemble_corpus: error: {exc}", file=sys.stderr)
        return 1
    what = "combined" if args.combined else args.county
    print(
        f"Assembled {what}: {docs} document(s), {tables} table(s) -> {args.output}\n"
        f"Next: cairn --config {Path(args.output) / 'cairn.toml'} index"
    )
    if args.allow_unreviewed:
        print("NOTE: unreviewed scaffolds were included. This is a smoke run, not a corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
