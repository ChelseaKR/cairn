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

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from cairn.language import normalize_code

REQUIRED_KEYS = ("id", "title", "lang")

# A doc id has to survive being written into an inline citation marker, and
# the interchange grammar for one is narrower than "any string": it starts
# with a letter and holds letters, digits, dot, underscore, colon and hyphen.
# Nothing enforced that, and the failure is silent in the worst direction — an
# id like `2024-winter-credit` or an Arabic-script id produces markers no
# consumer recognises as citations at all, so every genuinely grounded answer
# in the evidence reads as uncited and the audit reports a fabrication problem
# that does not exist.
#
# `#` is excluded for a second reason: it is the separator between a doc id
# and a passage ordinal, and `citation_marker` rewrites every `#` in the id.
# Doc ids `a#b` and `a.b` are distinct documents that both emit `[a.b.2]`, so
# a marker would resolve to whichever of the two a reader guessed.
DOC_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]*$")


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
    if not DOC_ID.match(doc_id):
        raise CorpusError(
            f"{path}: doc id {doc_id!r} cannot be written as a citation. An id "
            f"must start with a letter and hold only letters, digits, '.', '_', "
            f"':' and '-' — that is the grammar of the inline citation marker "
            f"every answer from this document will carry. An id outside it "
            f"produces markers nothing recognises as citations, so grounded "
            f"answers read as uncited."
        )
    title = meta["title"]
    # Normalised here and nowhere else. Retrieval scopes a search by comparing
    # this string exactly (`passage.lang != lang`), while `direction_of`
    # already ignores subtags — so `lang: en-GB` was a language of its own for
    # scoping and plain English for layout, and an English question against an
    # `en-GB` document came back with "the only source I have for this is
    # written in another language (en-GB)". One front-matter subtag, a
    # permanently false grounding claim on every answer from that document.
    lang = normalize_code(meta["lang"])
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


def corpus_paths(corpus_dir: str | Path) -> list[Path]:
    """The files the corpus is made of, in a fixed order.

    One definition, two callers: :func:`load_corpus` reads these and
    :func:`fingerprint` hashes them. Written out separately because a
    fingerprint over a *different* set of files than the loader reads is worse
    than no fingerprint at all — it would report "unchanged" across an edit to
    a document the index was built from, which is the exact failure the
    fingerprint exists to catch, now with a check standing behind it.
    """
    root = Path(corpus_dir)
    if not root.is_dir():
        raise CorpusError(f"corpus directory not found: {root}")
    paths = sorted(p for p in root.glob("*.md") if p.name.lower() != "readme.md")
    if not paths:
        raise CorpusError(f"no corpus documents (*.md) found in {root}")
    return paths


def fingerprint(corpus_dir: str | Path) -> str:
    """A hash of exactly the bytes :func:`load_corpus` would read.

    Hashed over raw bytes rather than over the parsed documents, deliberately.
    A parsed fingerprint would call a whitespace edit "unchanged", which is
    true of the index and false of the document — and every direction this can
    be wrong in should be the direction that says *re-index*. Re-indexing is
    cheap; quoting last week's text under this week's citation is not.

    File *names* are hashed alongside their contents, so renaming a document
    or adding one moves the fingerprint even when no byte of prose changed.
    The directory's own path is not, so an index built here still verifies
    against the same corpus unpacked somewhere else.
    """
    digest = hashlib.sha256()
    for path in corpus_paths(corpus_dir):
        raw = path.read_bytes()
        # Length-prefixed, so no arrangement of names and contents can be
        # rearranged into the same byte stream.
        digest.update(f"{len(path.name)}:{len(raw)}:".encode())
        digest.update(path.name.encode("utf-8"))
        digest.update(raw)
    return digest.hexdigest()


def load_corpus(corpus_dir: str | Path) -> list[Document]:
    """Load every ``*.md`` document under ``corpus_dir`` (non-recursive is
    deliberate: a corpus directory is flat and auditable at a glance).

    Documents are returned sorted by doc id so every downstream artifact is
    deterministic. Duplicate doc ids are an error, not a silent overwrite.
    """
    docs = [load_document(p) for p in corpus_paths(corpus_dir)]
    seen: dict[str, str] = {}
    for doc in docs:
        if doc.doc_id in seen:
            raise CorpusError(
                f"duplicate doc id {doc.doc_id!r} in {doc.path} "
                f"(already used by {seen[doc.doc_id]})"
            )
        seen[doc.doc_id] = doc.path
    return sorted(docs, key=lambda d: d.doc_id)
