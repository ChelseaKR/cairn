"""Corpus import scaffold: turn a .txt or .html file into a reviewable,
front-matter markdown scaffold — never a corpus input format Cairn reads.

`cairn index` reads exactly one format: markdown with a minimal front-matter
block (see `cairn/corpus.py`). This script never changes that, and it is not
wired into `cairn index` or any runtime path — it is a one-time, offline,
stdlib-only preprocessing convenience for migrating existing text (PDF-
derived text, a web page, a plain notice) into that format, with a
mandatory human-review step before the output is a real corpus document.

Nothing here guesses a doc id and ships it quietly: the placeholder id is
prefixed `review-` and stays that way until a human renames it. Ids are
citation-load-bearing (see `cairn/corpus.py`, `DOC_ID`) and should never be
auto-assigned as if they were final.

After writing the scaffold, this script loads it back through
`cairn.corpus.load_document` — the exact function `cairn index` calls — and
prints the passage boundaries that call actually produced, so what an
author reviews is exactly what indexing would do with it, not a second,
possibly-drifting idea of what "a paragraph" means.

Usage:
    python3 import_corpus.py notice.txt -o corpus/mine/notice.md --lang en
    python3 import_corpus.py page.html -o corpus/mine/page.md --title "..."
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from cairn.corpus import CorpusError, load_document

_SLUG_RE = re.compile(r"[^a-z0-9._:-]+")


def slugify(text: str) -> str:
    """A string that satisfies `cairn.corpus.DOC_ID`: starts with a letter,
    holds only letters, digits, `.`, `_`, `:`, `-`."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"doc-{slug}" if slug else "doc"
    return slug


class _ParagraphExtractor(HTMLParser):
    """Naive HTML-to-paragraphs: text is split on block-level tag
    boundaries; everything inside `<script>`/`<style>`/`<nav>`/`<head>` is
    dropped. Not a general-purpose HTML reader — good enough for a page a
    human is about to review paragraph by paragraph regardless.
    """

    _BLOCK_TAGS = {
        "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br",
        "tr", "section", "article", "header", "footer",
    }
    _SKIP_TAGS = {"script", "style", "head", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.title: str | None = None
        self._current: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def _flush(self) -> None:
        text = " ".join(" ".join(self._current).split())
        if text:
            self.paragraphs.append(text)
        self._current = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            # Checked ahead of `_skip_depth`: `<title>` lives inside `<head>`,
            # which is itself a skip tag for body text, but the title is not
            # body text and must not be swallowed by that same guard.
            self.title = (self.title or "") + data
            return
        if self._skip_depth:
            return
        self._current.append(data)

    def close(self) -> None:
        self._flush()
        super().close()


def extract_html(text: str) -> tuple[list[str], str | None]:
    parser = _ParagraphExtractor()
    parser.feed(text)
    parser.close()
    title = parser.title.strip() if parser.title else None
    return parser.paragraphs, (title or None)


def extract_text(text: str) -> list[str]:
    """Plain text, already assumed paragraph-delimited by blank lines — the
    same convention `cairn.corpus._chunk` reads."""
    blocks = re.split(r"\n\s*\n", text.strip())
    return [" ".join(b.split()) for b in blocks if b.strip()]


def build_scaffold(paragraphs: list[str], *, doc_id: str, title: str, lang: str) -> str:
    """The scaffold's front matter carries one extra key, `review`, that
    `cairn.corpus` never reads (only `id`, `title`, `lang`, and `synthetic`
    are) — front matter accepts unknown keys silently, which is exactly
    what an inert, human-visible marker needs. The review reminder itself
    is never written into the body: `cairn.corpus._chunk` would turn any
    body text into a real, retrievable, scored passage the moment this file
    is indexed, and a reviewer's own note becoming a quotable "passage" is
    the last thing this scaffold should risk.
    """
    body = "\n\n".join(paragraphs)
    return (
        "---\n"
        f"id: {doc_id}\n"
        f"title: {title}\n"
        f"lang: {lang}\n"
        "synthetic: false\n"
        "review: unreviewed\n"
        "---\n"
        f"{body}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a front-matter markdown corpus document from .txt or .html."
    )
    parser.add_argument("input", help="a .txt or .html file")
    parser.add_argument(
        "-o", "--output", required=True, help="path to write the .md scaffold to"
    )
    parser.add_argument(
        "--id",
        dest="doc_id",
        default=None,
        help="doc id (default: review-<slug of title or filename>)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="document title (default: <title> tag for HTML, filename for text)",
    )
    parser.add_argument("--lang", default="en", help="language code (default: en)")
    args = parser.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        print(f"import_corpus: error: no such file: {src}", file=sys.stderr)
        return 1
    raw = src.read_text(encoding="utf-8", errors="replace")

    if src.suffix.lower() in (".htm", ".html"):
        paragraphs, html_title = extract_html(raw)
        default_title = html_title or src.stem
    else:
        paragraphs = extract_text(raw)
        default_title = src.stem

    if not paragraphs:
        print("import_corpus: error: no paragraph text extracted", file=sys.stderr)
        return 1

    title = args.title or default_title
    doc_id = args.doc_id or f"review-{slugify(title)}"

    scaffold = build_scaffold(paragraphs, doc_id=doc_id, title=title, lang=args.lang)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scaffold, encoding="utf-8")

    print(f"Wrote {out_path} ({len(paragraphs)} paragraph(s) extracted)")
    print(
        "REVIEW REQUIRED before this is a real corpus document: check the doc id "
        f"(still prefixed 'review-' unless --id was given: {doc_id!r}), the title, "
        "the language, the synthetic flag, and every paragraph boundary shown "
        "below. Then delete the 'review: unreviewed' front-matter line — it is "
        "inert to Cairn, a marker for a human only."
    )

    try:
        doc = load_document(out_path)
    except CorpusError as exc:
        print(
            f"WARNING: the scaffold does not load as a valid document: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Chunk preview ({len(doc.passages)} passage(s), via cairn.corpus.load_document):")
    for p in doc.passages:
        preview = " ".join(p.text.split())
        if len(preview) > 70:
            preview = preview[:69] + "…"
        print(f"  {p.passage_id}: {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
