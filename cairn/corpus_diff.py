"""Corpus comparison: what changed between two corpus directories.

Compares by document id: added, removed, or changed (by the same passage
text `cairn index` would read), and for a changed document, which passage
ordinals now hold different text than before. Inserting or deleting a
paragraph renumbers every passage after it, which silently invalidates any
existing citation id (`doc-id#N`) built on the old numbering — a bookmarked
answer, a prior audit record, an external link — and a positional diff shows
exactly that: every ordinal from the edit point onward reads as "changed",
which is the accurate statement even when only one paragraph actually moved.

Read-only and advisory. This reports what changed; it has no opinion on
whether the change is safe, and it never tries to re-align ordinals across
an insertion to guess which old passage "became" which new one — that
judgment call, made silently, is the same mechanism the rejected corpus
alias experiment failed under (DESIGN.md, "Tried and rejected: declared
aliases on a document"), applied to passage identity instead of scoring.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from cairn.corpus import CorpusError, Document, load_corpus


@dataclass(frozen=True)
class PassageShift:
    ordinal: int
    old_text: str | None  # None when this ordinal is new
    new_text: str | None  # None when this ordinal no longer exists


@dataclass(frozen=True)
class DocumentDiff:
    doc_id: str
    kind: str  # "added" | "removed" | "changed"
    passage_shifts: tuple[PassageShift, ...] = ()


def _content_hash(doc: Document) -> str:
    body = "\n\n".join(p.text for p in doc.passages)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _passage_shifts(old: Document, new: Document) -> tuple[PassageShift, ...]:
    length = max(len(old.passages), len(new.passages))
    shifts = []
    for i in range(length):
        old_text = old.passages[i].text if i < len(old.passages) else None
        new_text = new.passages[i].text if i < len(new.passages) else None
        if old_text != new_text:
            shifts.append(PassageShift(ordinal=i + 1, old_text=old_text, new_text=new_text))
    return tuple(shifts)


def _has_any_document(root: Path) -> bool:
    return any(p.name.lower() != "readme.md" for p in root.glob("*.md"))


def _load(dir_path: str | Path) -> dict[str, Document]:
    """Every document under `dir_path`, by doc id.

    `load_corpus` refuses a directory with no `*.md` documents in it, which
    is right for something about to answer questions and wrong here: a
    corpus that has not been written yet, or one whose last document was
    just deleted, is a real and legitimate side of a diff, not an error. The
    glob here is a pre-check only — the actual loading still goes through
    `load_corpus`, so what counts as a document is decided in exactly one
    place.
    """
    root = Path(dir_path)
    if not root.is_dir():
        raise CorpusError(f"corpus directory not found: {root}")
    if not _has_any_document(root):
        return {}
    return {d.doc_id: d for d in load_corpus(root)}


def diff_corpora(old_dir: str | Path, new_dir: str | Path) -> tuple[DocumentDiff, ...]:
    old_docs = _load(old_dir)
    new_docs = _load(new_dir)

    diffs: list[DocumentDiff] = []
    for doc_id in sorted(set(new_docs) - set(old_docs)):
        diffs.append(DocumentDiff(doc_id, "added"))
    for doc_id in sorted(set(old_docs) - set(new_docs)):
        diffs.append(DocumentDiff(doc_id, "removed"))
    for doc_id in sorted(set(old_docs) & set(new_docs)):
        old, new = old_docs[doc_id], new_docs[doc_id]
        if _content_hash(old) != _content_hash(new):
            diffs.append(DocumentDiff(doc_id, "changed", _passage_shifts(old, new)))
    return tuple(diffs)


def render(diffs: tuple[DocumentDiff, ...]) -> str:
    if not diffs:
        return "No document changes."
    lines = [f"{len(diffs)} document(s) differ:"]
    for d in diffs:
        lines.append(f"  {d.kind:7} {d.doc_id}")
        for shift in d.passage_shifts:
            passage_id = f"{d.doc_id}#{shift.ordinal}"
            if shift.old_text is None:
                lines.append(f"      {passage_id}: new passage")
            elif shift.new_text is None:
                lines.append(
                    f"      {passage_id}: no longer exists — any citation to it now "
                    f"points at nothing"
                )
            else:
                lines.append(f"      {passage_id}: text differs from before")
    lines.append(
        "Advisory only: this reports what changed, not whether it is safe to publish."
    )
    return "\n".join(lines)
