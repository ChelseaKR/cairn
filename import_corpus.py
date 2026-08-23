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
import json
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
    """HTML to the paragraph shape `cairn.corpus._chunk` reads.

    The first version split on every block tag and dropped only
    `<script>`/`<style>`/`<nav>`/`<head>`. Run over 28 real federal pages on
    2026-08-23 that produced ~120 "paragraphs" per page: every menu entry,
    footer link, list item and table row became its own passage, and a row
    reading `Individual $1,350 $9,950` — a real 2026 Medicare Savings Program
    limit — was a passage holding no word that any question about it would
    use. `docs/pilot-usagov.md` transcribed by hand into the shape that
    works: a `##` heading, then the paragraph or the whole list under it as
    one block. This extractor produces that shape mechanically, in four
    rules, each of which a reviewer can see the effect of in the preview:

    - **Scope to the main content** when the page marks it (`<main>`, or
      `role="main"`); header, footer, aside, nav and form controls are
      dropped whether or not it does. A page with no `<main>` is read
      whole, as before — a reviewer deletes what is left.
    - **Headings become `#` lines** (`<h2>` to `##`, and so on), in their
      own block, so the chunker attaches each to the passage it introduces.
      The `<h1>` is taken as the title candidate instead — the page's own
      name beats a `<title>` tag's `Page | Site | Department` suffix chain.
    - **A list is one block.** Its items are joined with a space when the
      item already ends in sentence punctuation and with `; ` otherwise;
      nothing is reworded. Nested lists flatten into their parent.
    - **A table is one block**, one line per row, cells joined by ` | `.
      A reviewer who finds a real income-limit table in one of these moves
      it to `tables/*.csv` (see `cairn/tabular.py`) or leaves it as prose;
      either way it arrives in one piece, under its heading.

    Still not a general-purpose HTML reader — good enough for a page a human
    is about to review paragraph by paragraph regardless.
    """

    # Not `form`: ASP.NET sites (cdss.ca.gov among them) wrap the entire
    # page body in one <form>, and skipping it skipped the page. Form
    # *controls* are skipped instead; a form's prose is prose.
    _SKIP_TAGS = {
        "script", "style", "head", "nav", "header", "footer", "aside",
        "button", "select", "option", "textarea", "input", "label",
        "noscript", "svg", "template",
    }
    _LANDMARK_TAGS = {"nav", "header", "footer", "aside"}
    _PARAGRAPH_TAGS = {"p", "div", "section", "article", "blockquote", "pre", "br", "hr"}
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _LIST_TAGS = {"ul", "ol", "dl"}
    _ITEM_TAGS = {"li", "dt", "dd"}
    _VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "wbr", "source", "track"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.title: str | None = None
        self.h1: str | None = None
        self._current: list[str] = []
        # Tags that opened a skipped region, innermost last. A region is
        # skipped for its tag name or for `aria-hidden="true"`, and since a
        # hidden <div> closes with </div>, the close has to be matched by
        # name rather than counted — the first version counted, and one
        # hidden <div> that wrapped a search form swallowed every page on
        # medicare.gov.
        self._skip_stack: list[str] = []
        self._in_title = False
        self._heading: str | None = None  # the heading tag currently open
        self._heading_text: list[str] = []
        self._list_depth = 0
        self._items: list[str] = []
        self._table_depth = 0
        self._rows: list[list[str]] = []
        self._cell: list[str] | None = None
        # Main-content scoping: once a <main> (or role="main") opens, only
        # text inside it counts, and everything before it is discarded.
        # role="main" usually sits on a <div>, so the close has to be the
        # matching </div> and not the first nested one: the tag name is
        # remembered and its nesting counted.
        self._main_tag: str | None = None
        self._main_depth = 0
        self._saw_main = False

    # --- block assembly -------------------------------------------------

    @staticmethod
    def _squash(parts: list[str]) -> str:
        return " ".join(" ".join(parts).split())

    def _emit(self, text: str) -> None:
        if text:
            self.paragraphs.append(text)

    def _flush(self) -> None:
        self._emit(self._squash(self._current))
        self._current = []

    def _flush_item(self) -> None:
        text = self._squash(self._current)
        self._current = []
        if text:
            self._items.append(text)

    def _flush_list(self) -> None:
        self._flush_item()
        if not self._items:
            return
        joined = ""
        for item in self._items:
            if not joined:
                joined = item
            elif joined.endswith((".", "!", "?", ":", ";")):
                joined = f"{joined} {item}"
            else:
                joined = f"{joined}; {item}"
        self._items = []
        self._emit(joined)

    def _flush_table(self) -> None:
        rows = [" | ".join(cells) for cells in self._rows if any(cells)]
        self._rows = []
        self._emit("\n".join(rows))

    # --- parser events --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if self._main_tag is not None and tag == self._main_tag:
            self._main_depth += 1
        elif tag == "main" or attributes.get("role") == "main":
            if not self._saw_main:
                # Everything before the main content was chrome.
                self.paragraphs = []
                self._current = []
                self._saw_main = True
            self._main_tag = tag
            self._main_depth = 1
            # Main content is never inside navigation. A <nav> left unclosed
            # (coveredca.com has one) would otherwise keep every word of the
            # page on the skip stack; the landmark tags are closed here and
            # the script/style kind are left alone.
            self._skip_stack = [t for t in self._skip_stack if t not in self._LANDMARK_TAGS]
        if tag in self._SKIP_TAGS or attributes.get("aria-hidden") == "true":
            if tag not in self._VOID_TAGS:
                self._skip_stack.append(tag)
            return
        if tag == "title":
            self._in_title = True
            return
        if self._skip_stack:
            return
        if tag in self._HEADING_TAGS:
            self._flush()
            self._heading = tag
            self._heading_text = []
        elif tag in self._LIST_TAGS:
            if self._list_depth == 0:
                self._flush()
            else:
                self._flush_item()
            self._list_depth += 1
        elif tag in self._ITEM_TAGS and self._list_depth:
            self._flush_item()
        elif tag == "table":
            self._flush()
            self._table_depth += 1
        elif tag == "tr" and self._table_depth:
            self._rows.append([])
        elif tag in ("td", "th") and self._table_depth:
            self._cell = []
        elif tag in self._PARAGRAPH_TAGS:
            if self._list_depth:
                # A <p> or <br> inside a list item stays in the item.
                self._current.append(" ")
            elif not self._table_depth:
                self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._main_tag is not None and tag == self._main_tag:
            self._main_depth -= 1
            if self._main_depth == 0:
                self._main_tag = None
        if tag == "title":
            # Before the skip check, for the same reason as in handle_data:
            # <title> sits inside <head>, which is a skipped region.
            self._in_title = False
            return
        if self._skip_stack:
            if tag in self._skip_stack:
                # Close the innermost region this tag opened, and with it any
                # inner region left unclosed by sloppy markup.
                index = len(self._skip_stack) - 1 - self._skip_stack[::-1].index(tag)
                del self._skip_stack[index:]
            return
        if tag in self._HEADING_TAGS and self._heading == tag:
            text = self._squash(self._heading_text)
            self._heading = None
            if tag == "h1":
                if self.h1 is None:
                    self.h1 = text
                # Emitted as body too; `drop_duplicated_title` removes it
                # when it is the title, and keeps it when a reviewer chose a
                # different title — a reviewer's choice is not overridden.
                self._emit(text)
            elif text:
                level = int(tag[1])
                self._emit(f"{'#' * level} {text}")
        elif tag in self._LIST_TAGS and self._list_depth:
            self._list_depth -= 1
            if self._list_depth == 0:
                self._flush_list()
            else:
                self._flush_item()
        elif tag in self._ITEM_TAGS and self._list_depth:
            self._flush_item()
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._flush_table()
        elif tag in ("td", "th") and self._table_depth and self._cell is not None:
            if self._rows:
                self._rows[-1].append(self._squash(self._cell))
            self._cell = None
        elif tag in self._PARAGRAPH_TAGS:
            if self._list_depth:
                self._current.append(" ")
            elif not self._table_depth:
                self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            # Checked ahead of the skip stack: `<title>` lives inside `<head>`,
            # which is itself a skip tag for body text, but the title is not
            # body text and must not be swallowed by that same guard.
            self.title = (self.title or "") + data
            return
        if self._skip_stack:
            return
        if self._saw_main and self._main_tag is None:
            return  # after </main>: chrome again
        if self._heading is not None:
            self._heading_text.append(data)
        elif self._cell is not None:
            self._cell.append(data)
        else:
            self._current.append(data)

    def close(self) -> None:
        self._flush_list() if self._list_depth else self._flush()
        super().close()


def tidy_blocks(blocks: list[str]) -> tuple[list[str], int]:
    """Two mechanical passes over extracted blocks, each one a thing the
    smoke run of 2026-08-23 showed retrieval rewarding for the wrong reason.

    A block ending in a colon is a list introducer — "If you qualify for the
    QMB program:" — and on its own it is short, names the program, and
    outscores the table under it that holds the numbers. It is joined to
    the block it introduces, which is what `docs/pilot-usagov.md`'s hand
    transcription did ("To check how much money is left on your EBT card:
    Check your receipt…"). Headings are never joined.

    A block of up to three words with no digit and no sentence punctuation
    — "Begin", "Next step", "Human Services Department", "Financial
    Assistance Home" — is page furniture: menu entries and breadcrumbs that
    survived inside `<main>` or sit on a page without one. As passages they
    answered "What vaccinations does my dog need?" and "Where do I apply for
    General Assistance?" on the smoke runs. Dropped, and the count is
    reported so the reviewer knows something was. A short block *with* a
    digit ("Individual $1,350") or a full stop ("Limits apply.") is kept.

    A short block that is a question — "Who Is Eligible?", six words or
    fewer — is a heading the page rendered as a paragraph (smcgov.org does
    this with `<p><strong>`), and alone it answered "Where do I apply for
    General Assistance?" ahead of the paragraph under it. It becomes a
    `##` line, so the chunker attaches it to that paragraph. A reviewer who
    disagrees removes two characters.
    """
    shaped: list[str] = []
    for block in blocks:
        words = block.split()
        if block.endswith("?") and len(words) <= 6 and not block.startswith("#"):
            shaped.append(f"## {block}")
        else:
            shaped.append(block)
    merged: list[str] = []
    for block in shaped:
        previous = merged[-1] if merged else ""
        if (
            previous.endswith(":")
            and not previous.startswith("#")
            and not block.startswith("#")
            and "\n" not in previous
        ):
            merged[-1] = f"{previous} {block}"
        else:
            merged.append(block)
    kept: list[str] = []
    dropped = 0
    for block in merged:
        words = block.split()
        furniture = (
            len(words) <= 3
            and not any(ch.isdigit() for ch in block)
            and not block.endswith((".", "!", "?", ":"))
        )
        if furniture and not block.startswith("#"):
            dropped += 1
            continue
        kept.append(block)
    return kept, dropped


def extract_html(text: str) -> tuple[list[str], str | None]:
    """Paragraphs and a title candidate: the first `<h1>` when the page has
    one, else the `<title>` tag."""
    parser = _ParagraphExtractor()
    parser.feed(text)
    parser.close()
    title = (parser.h1 or (parser.title.strip() if parser.title else "")).strip()
    return parser.paragraphs, (title or None)


def extract_text(text: str) -> list[str]:
    """Plain text, already assumed paragraph-delimited by blank lines — the
    same convention `cairn.corpus._chunk` reads."""
    blocks = re.split(r"\n\s*\n", text.strip())
    return [" ".join(b.split()) for b in blocks if b.strip()]


def _normalise_heading(text: str) -> str:
    """Case-folded, whitespace-collapsed, trailing punctuation dropped — the
    comparison under which a page's own H1 and its `<title>` are "the same
    line" even when one carries a trailing period or a site-name suffix is
    *not* stripped (that is a judgement, and judgements stay with the
    reviewer)."""
    return " ".join(text.casefold().split()).rstrip(" .:!?")


def drop_duplicated_title(paragraphs: list[str], title: str) -> tuple[list[str], bool]:
    """Drop a leading paragraph that is the document's own title restated.

    `docs/pilot-usagov.md`, Finding 1: a page transcribed faithfully shows its
    own heading as the first line of body text, so the scaffold's first
    passage was the title repeated — short, generic, lexically present in
    almost any question about the page, and exactly the shape TF-IDF cosine's
    length normalisation rewards. It out-scored the real answering passage on
    a real question. The title is not lost by dropping it: the front-matter
    `title:` field is already weighted into every passage's score.

    The pilot recorded this as review guidance. It is mechanical — there is
    no judgement in "this paragraph is the title" — so guidance that every
    importer has to remember is the wrong place for it. Any block that is
    exactly the title (normalised) is dropped, not only the first: a page
    with no `<main>` puts its breadcrumbs first and its restated title
    third, and sonomacounty.gov answered a question with that third block.
    A block that *contains* the title inside a real sentence is content and
    stays. Returns the kept blocks and whether anything was dropped.
    """
    wanted = _normalise_heading(title)
    kept = [block for block in paragraphs if _normalise_heading(block) != wanted]
    return kept, len(kept) != len(paragraphs)


def build_scaffold(
    paragraphs: list[str],
    *,
    doc_id: str,
    title: str,
    lang: str,
    source: str | None = None,
    fetched_at: str | None = None,
) -> str:
    """The scaffold's front matter carries extra keys that `cairn.corpus`
    never reads (only `id`, `title`, `lang`, and `synthetic` are) — front
    matter accepts unknown keys silently, which is exactly what inert,
    human-visible markers need. `review` is the reviewer's to delete;
    `source` and `fetched_at` are provenance, written here from the fetch
    manifest so a URL is never retyped by hand (the usa.gov pilot typed six
    by hand; a real corpus has hundreds). `reviewed_at` is deliberately
    *not* written: it records that a person read the document, and the
    scaffold has no business asserting that.

    The review reminder itself is never written into the body:
    `cairn.corpus._chunk` would turn any body text into a real, retrievable,
    scored passage the moment this file is indexed, and a reviewer's own
    note becoming a quotable "passage" is the last thing this scaffold
    should risk.
    """
    body = "\n\n".join(paragraphs)
    provenance = ""
    if source:
        provenance += f"source: {source}\n"
    if fetched_at:
        provenance += f"fetched_at: {fetched_at}\n"
    return (
        "---\n"
        f"id: {doc_id}\n"
        f"title: {title}\n"
        f"lang: {lang}\n"
        "synthetic: false\n"
        f"{provenance}"
        "review: unreviewed\n"
        "---\n"
        f"{body}\n"
    )


def scaffold_one(
    src: Path,
    out_path: Path,
    *,
    doc_id: str | None,
    title: str | None,
    lang: str,
    source: str | None = None,
    fetched_at: str | None = None,
) -> tuple[int, int]:
    """Scaffold one input file to `out_path`. Returns `(exit_code,
    paragraph_count)` — the single source both `--batch` and the one-file
    path go through, so scaffolding a directory of files is never a second,
    drifting idea of what scaffolding one file does.
    """
    if not src.is_file():
        print(f"import_corpus: error: no such file: {src}", file=sys.stderr)
        return 1, 0
    raw = src.read_text(encoding="utf-8", errors="replace")

    is_html = src.suffix.lower() in (".htm", ".html")
    if is_html:
        paragraphs, html_title = extract_html(raw)
        default_title = html_title or src.stem
    else:
        paragraphs = extract_text(raw)
        default_title = src.stem

    if not paragraphs:
        print(f"import_corpus: error: no paragraph text extracted from {src}", file=sys.stderr)
        return 1, 0

    resolved_title = title or default_title
    resolved_id = doc_id or f"review-{slugify(resolved_title)}"

    # Title dedup first, then tidying: the tidy pass drops short fragments,
    # and a restated title is exactly the short fragment whose removal
    # should be reported as the title, not as furniture.
    paragraphs, dropped_title = drop_duplicated_title(paragraphs, resolved_title)
    fragments_dropped = 0
    if is_html:
        paragraphs, fragments_dropped = tidy_blocks(paragraphs)
    if not paragraphs:
        print(
            f"import_corpus: error: {src} holds nothing but its own title as body text",
            file=sys.stderr,
        )
        return 1, 0

    scaffold = build_scaffold(
        paragraphs,
        doc_id=resolved_id,
        title=resolved_title,
        lang=lang,
        source=source,
        fetched_at=fetched_at,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scaffold, encoding="utf-8")

    print(f"Wrote {out_path} ({len(paragraphs)} paragraph(s) extracted)")
    if fragments_dropped:
        print(
            f"Dropped {fragments_dropped} one-or-two-word fragment(s) with no digit "
            f"(page furniture such as 'Next step'); check the source if one was content."
        )
    if dropped_title:
        print(
            "Dropped the first paragraph: it restated the title verbatim "
            "(docs/pilot-usagov.md, Finding 1). The title survives as front matter."
        )
    print(
        "REVIEW REQUIRED before this is a real corpus document: check the doc id "
        f"(still prefixed 'review-' unless --id was given: {resolved_id!r}), the title, "
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
        return 1, len(paragraphs)

    print(f"Chunk preview ({len(doc.passages)} passage(s), via cairn.corpus.load_document):")
    for p in doc.passages:
        preview = " ".join(p.text.split())
        if len(preview) > 70:
            preview = preview[:69] + "…"
        print(f"  {p.passage_id}: {preview}")
    return 0, len(paragraphs)


def _batch_sources(src_dir: Path) -> list[Path]:
    """Every `.txt`/`.html` file directly in `src_dir` — non-recursive, the
    same flat-directory convention `cairn.corpus.corpus_paths` uses for the
    real corpus, so batch output maps predictably onto a real corpus layout.
    """
    return sorted(
        p
        for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".txt", ".html", ".htm")
    )


MANIFEST_NAME = "manifest.json"


def load_manifest(src_dir: Path) -> dict[str, dict]:
    """The fetch manifest `fetch_pages.py` writes beside the pages it saved,
    keyed by file name. Absent is fine — a directory of hand-saved pages has
    no manifest and gets no provenance, which is honest. Present and
    unreadable is an error, because a manifest that is there and ignored
    would silently scaffold a whole batch without the provenance it carries.
    """
    path = src_dir / MANIFEST_NAME
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    pages = data.get("pages", [])
    return {page["file"]: page for page in pages if "file" in page}


def run_batch(src_dir: Path, out_dir: Path, *, lang: str) -> int:
    if not src_dir.is_dir():
        print(f"import_corpus: error: not a directory: {src_dir}", file=sys.stderr)
        return 1
    sources = _batch_sources(src_dir)
    if not sources:
        print(f"import_corpus: error: no .txt or .html files in {src_dir}", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(src_dir)
    except (OSError, ValueError) as exc:
        print(f"import_corpus: error: unreadable {MANIFEST_NAME}: {exc}", file=sys.stderr)
        return 1
    if manifest:
        print(f"Provenance from {src_dir / MANIFEST_NAME} ({len(manifest)} page(s) listed)")

    failed = 0
    total_paragraphs = 0
    for src in sources:
        print(f"--- {src.name} ---")
        entry = manifest.get(src.name, {})
        # The placeholder id comes from the file name, not the title: four
        # cdss.ca.gov pages share the H1 "CalFresh", and ids that collide
        # are ids assembly refuses. File names in a batch are unique by
        # construction (fetch_pages.py derives them), and the `review-`
        # prefix still says a person has to choose the real one.
        code, paragraph_count = scaffold_one(
            src,
            out_dir / f"{src.stem}.md",
            doc_id=f"review-{slugify(src.stem)}",
            title=None,
            lang=entry.get("lang") or lang,
            source=entry.get("url"),
            fetched_at=entry.get("fetched_at"),
        )
        if code != 0:
            failed += 1
        else:
            total_paragraphs += paragraph_count
        print()

    print(
        f"Batch: {len(sources) - failed}/{len(sources)} file(s) scaffolded, "
        f"{total_paragraphs} paragraph(s) total."
    )
    if failed:
        print(f"{failed} file(s) failed to scaffold — see the errors above.", file=sys.stderr)
    print("REVIEW REQUIRED for every file above before any of them is a real corpus document.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold front-matter markdown corpus document(s) from .txt or .html."
    )
    parser.add_argument(
        "input", help="a .txt or .html file, or (with --batch) a directory of them"
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="path to write the .md scaffold to (with --batch: the output directory)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help=(
            "treat 'input' as a directory: scaffold every .txt/.html file in it "
            "(non-recursive) into --output, one .md per source file. --id and "
            "--title do not apply — each file's id/title is derived the same way "
            "the one-file path derives them when neither is given."
        ),
    )
    parser.add_argument(
        "--id",
        dest="doc_id",
        default=None,
        help="doc id (default: review-<slug of title or filename>); not valid with --batch",
    )
    parser.add_argument(
        "--title",
        default=None,
        help=(
            "document title (default: <title> tag for HTML, filename for text); "
            "not valid with --batch"
        ),
    )
    parser.add_argument("--lang", default="en", help="language code (default: en)")
    parser.add_argument(
        "--source",
        default=None,
        help=(
            "URL the page was fetched from, written as inert `source:` front matter; "
            "not valid with --batch, which reads it from fetch_pages.py's manifest.json"
        ),
    )
    args = parser.parse_args(argv)

    if args.batch:
        if args.doc_id or args.title or args.source:
            print(
                "import_corpus: error: --id, --title and --source are not valid with --batch",
                file=sys.stderr,
            )
            return 1
        return run_batch(Path(args.input), Path(args.output), lang=args.lang)

    code, _ = scaffold_one(
        Path(args.input),
        Path(args.output),
        doc_id=args.doc_id,
        title=args.title,
        lang=args.lang,
        source=args.source,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
