"""Corpus loading and chunking.

Corpus documents are Markdown files carrying a minimal front-matter block:

    ---
    id: grocery-allowance-en
    title: Fresh Start Grocery Allowance
    lang: en
    synthetic: true
    ---
    body...

The front matter is a strict ``key: value`` list between two ``---`` lines at
the top of the file. Cairn parses it itself; there is no YAML dependency.

Chunking splits the body into passages on blank-line paragraph boundaries.
Heading-only blocks are merged into the passage that follows them: a heading
is context for its section, not a retrievable unit of its own. Passage ids
are ``<doc-id>#<ordinal>`` (ordinals start at 1), which stay stable as long
as the document's paragraph structure is stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = ("id", "title", "lang")


class CorpusError(ValueError):
    """A corpus document is malformed or the corpus directory is unusable."""


@dataclass(frozen=True)
class Passage:
    passage_id: str
    doc_id: str
    title: str
    lang: str
    text: str


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    lang: str
    synthetic: bool
    path: str
    passages: tuple[Passage, ...]


def _parse_front_matter(raw: str, path: Path) -> tuple[dict[str, str], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CorpusError(f"{path}: missing front-matter block (file must start with ---)")
    meta: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[i + 1 :])
            return meta, body
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise CorpusError(f"{path}: bad front-matter line {i + 1}: {line!r}")
        meta[key.strip()] = value.strip()
    raise CorpusError(f"{path}: front-matter block never closed with ---")


def _chunk(body: str, doc_id: str, title: str, lang: str) -> tuple[Passage, ...]:
    blocks: list[str] = []
    pending_heading: list[str] = []
    for raw_block in body.split("\n\n"):
        block = raw_block.strip()
        if not block:
            continue
        if all(line.lstrip().startswith("#") for line in block.splitlines()):
            pending_heading.append(block)
            continue
        if pending_heading:
            block = "\n".join([*pending_heading, block])
            pending_heading = []
        blocks.append(block)
    # A trailing heading with no content after it is dropped: nothing to ground on.
    return tuple(
        Passage(
            passage_id=f"{doc_id}#{ordinal}",
            doc_id=doc_id,
            title=title,
            lang=lang,
            text=block,
        )
        for ordinal, block in enumerate(blocks, start=1)
    )


def load_document(path: Path) -> Document:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
    if missing:
        raise CorpusError(f"{path}: front matter missing required key(s): {', '.join(missing)}")
    doc_id = meta["id"]
    title = meta["title"]
    lang = meta["lang"]
    passages = _chunk(body, doc_id=doc_id, title=title, lang=lang)
    if not passages:
        raise CorpusError(f"{path}: document has no body passages to index")
    return Document(
        doc_id=doc_id,
        title=title,
        lang=lang,
        synthetic=meta.get("synthetic", "").casefold() == "true",
        path=str(path),
        passages=passages,
    )


def load_corpus(corpus_dir: str | Path) -> list[Document]:
    """Load every ``*.md`` document under ``corpus_dir`` (non-recursive is
    deliberate: a corpus directory is flat and auditable at a glance).

    Documents are returned sorted by doc id so every downstream artifact is
    deterministic. Duplicate doc ids are an error, not a silent overwrite.
    """
    root = Path(corpus_dir)
    if not root.is_dir():
        raise CorpusError(f"corpus directory not found: {root}")
    paths = sorted(p for p in root.glob("*.md") if p.name.lower() != "readme.md")
    if not paths:
        raise CorpusError(f"no corpus documents (*.md) found in {root}")
    docs = [load_document(p) for p in paths]
    seen: dict[str, str] = {}
    for doc in docs:
        if doc.doc_id in seen:
            raise CorpusError(
                f"duplicate doc id {doc.doc_id!r} in {doc.path} "
                f"(already used by {seen[doc.doc_id]})"
            )
        seen[doc.doc_id] = doc.path
    return sorted(docs, key=lambda d: d.doc_id)
