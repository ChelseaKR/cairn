"""Fetch a declared list of public web pages into a directory, with a manifest.

Dev-only, stdlib-only, never part of the runtime and never wired into
`cairn index`. The real corpus pilot (`docs/pilot-ca.md`) needs a few hundred
pages from federal, state and county sites, and the usa.gov pilot before it
typed six URLs into front matter by hand. At hundreds, a URL typed by hand is
a URL that will be wrong, and a page saved without the date it was saved is a
page whose staleness nobody can later measure. So this script does the one
thing the browser's "save as" cannot: it writes down, for every page, where
it came from, when, and what bytes arrived — and `import_corpus.py --batch`
reads that manifest back so provenance reaches the scaffold untouched.

What it reads: a TOML source list, one per corpus layer::

    layer = "california"
    terms = "https://www.ca.gov/use/"     # the conditions-of-use page
    terms_checked = "2026-08-23"          # the day a person read it
    terms_note = "state content public domain unless otherwise noted"

    [[page]]
    url = "https://www.cdss.ca.gov/food-nutrition/calfresh"
    lang = "en"
    program = "calfresh"
    file = "calfresh-overview-en"         # optional; derived from the URL otherwise

What it writes: `<out>/<file>.html` for each page and `<out>/manifest.json`,
which records every page it was asked for — fetched or failed — with the
URL, the SHA-256 of the bytes, the fetch date, the HTTP status, and the
layer's terms. A failed page is a manifest entry with `status` and `error`
set and no file, never a silent gap in the batch.

Terms are not checked by this script; they are declared by the person who
read them, and the declaration travels with the pages. A source list with no
`terms` entry refuses to run: a layer whose conditions of use nobody has
looked at is not a layer this pilot fetches from. A source list with
`blocked = "<reason>"` refuses to run too, and that is the shape a layer
takes when someone read the terms and they said no — the URLs stay listed,
the reason stays with them, and nothing is fetched until a person removes
the key and says why. Federal sites are public domain by statute
(17 U.S.C. §105); California state and county sites each carry their own
terms, which is exactly why the field is mandatory.

Politeness: one request at a time, a pause between requests, a User-Agent
that names this project and where to find it, and no retries — a page that
failed is reported, and a person decides whether to try again. Already-saved
pages are skipped unless `--refresh` is given, so re-running to pick up a
few failures does not re-fetch everything.

Some sites refuse every non-browser client (ssa.gov and fcc.gov answered 403
to this script and to a browser user-agent string alike on 2026-08-23;
studentaid.gov drops this script's user agent specifically; dhcs.ca.gov
serves a bot-challenge stub). Those pages get saved from a real browser
into the same directory under the file name the source list derives —
either by a person, or by `browser_save.mjs`, which drives Chromium
through Playwright and needs `--browser-jobs` first to know what to save.
`--hand-saved` then records whatever is there: SHA-256, today's date, and
`status: "hand-saved"` instead of an HTTP status, plus `saved_by` and the
URL the browser actually landed on when `browser_save.mjs` left its
sidecar. The manifest says plainly which pages this script fetched, which a
browser did, and which a person did. Nothing is requested over the network
in either of those modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "cairn-pilot-fetch/0.1 (+https://github.com/ChelseaKR/cairn; corpus research)"
MANIFEST_NAME = "manifest.json"
JOBS_NAME = "browser-jobs.json"
BROWSER_SIDECAR = "browser-saved.json"
# A 200 with almost nothing in it is not a page. dhcs.ca.gov answered this
# script with 205 bytes of Incapsula bot-challenge JavaScript and a 200, and
# a manifest that called that "fetched" would scaffold an empty document
# with a real URL in its front matter.
MIN_PAGE_BYTES = 1500
DEFAULT_PAUSE_SECONDS = 1.5
DEFAULT_TIMEOUT_SECONDS = 30

_FILE_RE = re.compile(r"[^a-z0-9-]+")


class SourceError(ValueError):
    """A source list that cannot be acted on. Raised before any request."""


@dataclass(frozen=True)
class Page:
    url: str
    file: str
    lang: str
    program: str | None


@dataclass(frozen=True)
class SourceList:
    layer: str
    terms: str
    terms_checked: str
    terms_note: str | None
    pages: tuple[Page, ...]


def file_stem_for(url: str, lang: str) -> str:
    """A stable, readable file name from a URL: the last two path segments
    and the language, so `/food-nutrition/calfresh` in Spanish becomes
    `food-nutrition-calfresh-es`. Stable matters more than pretty — the
    name is the join key between the manifest and the scaffold."""
    path = urlparse(url).path.strip("/")
    segments = [s for s in path.split("/") if s] or [urlparse(url).netloc]
    stem = "-".join(segments[-2:]).lower()
    stem = _FILE_RE.sub("-", stem).strip("-") or "page"
    return f"{stem}-{lang}"


def load_sources(path: str | Path) -> SourceList:
    file = Path(path)
    if not file.is_file():
        raise SourceError(f"no source list at {file}")
    with open(file, "rb") as handle:
        data = tomllib.load(handle)
    layer = data.get("layer")
    if not layer:
        raise SourceError(f"{file}: missing 'layer'")
    terms = data.get("terms")
    checked = data.get("terms_checked")
    blocked = data.get("blocked")
    if blocked:
        raise SourceError(
            f"{file}: layer {layer!r} is blocked: {blocked}\n"
            f"A layer whose terms forbid reuse is not fetched. Remove 'blocked' only "
            f"once the terms changed or written permission is on file (say where)."
        )
    if not terms or not checked:
        raise SourceError(
            f"{file}: layer {layer!r} declares no 'terms' / 'terms_checked'. A layer "
            f"whose conditions of use nobody has read is not fetched from; read the "
            f"site's terms page, record its URL and today's date, then run again."
        )
    raw_pages = data.get("page", [])
    if not raw_pages:
        raise SourceError(f"{file}: no [[page]] entries")
    pages: list[Page] = []
    seen_files: set[str] = set()
    seen_urls: set[str] = set()
    for entry in raw_pages:
        url = entry.get("url")
        if not url or urlparse(url).scheme not in ("http", "https"):
            raise SourceError(f"{file}: a page is missing a usable 'url' ({url!r})")
        lang = entry.get("lang", "en")
        stem = entry.get("file") or file_stem_for(url, lang)
        if stem in seen_files:
            raise SourceError(
                f"{file}: two pages resolve to the file name {stem!r}; give one a 'file'"
            )
        if url in seen_urls:
            raise SourceError(f"{file}: {url} is listed twice")
        seen_files.add(stem)
        seen_urls.add(url)
        pages.append(Page(url=url, file=stem, lang=lang, program=entry.get("program")))
    return SourceList(
        layer=layer,
        terms=terms,
        terms_checked=str(checked),
        terms_note=data.get("terms_note"),
        pages=tuple(pages),
    )


Fetcher = Callable[[str], tuple[int, bytes]]


def fetch_url(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, bytes]:
    """One GET. Returns `(status, body)`; an HTTP error is returned as its
    status with whatever body came with it rather than raised, because the
    manifest wants the status either way."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() if exc.fp else b""


def _read_manifest(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {entry["file"]: entry for entry in data.get("pages", [])}


def _write_manifest(path: Path, sources: SourceList, entries: dict[str, dict]) -> None:
    payload = {
        "layer": sources.layer,
        "terms": sources.terms,
        "terms_checked": sources.terms_checked,
        "terms_note": sources.terms_note,
        "pages": [entries[key] for key in sorted(entries)],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _outstanding(sources: SourceList, out_dir: Path, entries: dict[str, dict]) -> list[Page]:
    """Pages with no successfully fetched or registered file."""
    out = []
    for page in sources.pages:
        target = out_dir / f"{page.file}.html"
        entry = entries.get(target.name, {})
        good = entry.get("status") in (200, "hand-saved") and "error" not in entry
        if target.is_file() and good:
            continue
        out.append(page)
    return out


def write_browser_jobs(
    sources: SourceList, out_dir: Path, *, log: Callable[[str], None] = print
) -> int:
    """Write the list of pages `browser_save.mjs` should save: every page the
    manifest does not already hold a good copy of. Returns the count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = _read_manifest(out_dir / MANIFEST_NAME)
    jobs = [
        {"file": f"{p.file}.html", "url": p.url, "lang": p.lang, "program": p.program}
        for p in _outstanding(sources, out_dir, entries)
    ]
    with open(out_dir / JOBS_NAME, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"layer": sources.layer, "jobs": jobs}, handle, indent=2)
        handle.write("\n")
    log(f"{sources.layer}: {len(jobs)} page(s) to save from a browser -> {out_dir / JOBS_NAME}")
    return len(jobs)


def _read_sidecar(out_dir: Path) -> dict[str, dict]:
    path = out_dir / BROWSER_SIDECAR
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        return dict(json.load(handle).get("saved", {}))


def register_hand_saved(
    sources: SourceList,
    out_dir: Path,
    *,
    today: str | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Record pages a browser saved. Returns how many were registered. A
    listed page with no file is reported, not invented; a page already in
    the manifest with a good copy is left alone. When `browser_save.mjs`
    left its sidecar, the entry also says so and carries the URL the
    browser actually landed on — a redirect to a login page is a fact the
    reviewer wants in front of them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / MANIFEST_NAME
    entries = _read_manifest(manifest_path)
    sidecar = _read_sidecar(out_dir)
    stamp = today or date.today().isoformat()
    registered = 0
    for page in _outstanding(sources, out_dir, entries):
        target = out_dir / f"{page.file}.html"
        if not target.is_file():
            log(f"  {page.file}: not saved (expected {target})")
            continue
        body = target.read_bytes()
        entry = {
            "file": target.name,
            "url": page.url,
            "lang": page.lang,
            "program": page.program,
            "layer": sources.layer,
            "terms": sources.terms,
            "terms_checked": sources.terms_checked,
            "fetched_at": stamp,
            "status": "hand-saved",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
        saved = sidecar.get(target.name)
        if saved and saved.get("error"):
            # browser_save.mjs saw an error for this file; whatever is on
            # disk is not the page. Leave it outstanding.
            log(f"  {page.file}: not registered ({saved['error']} in the browser)")
            continue
        if saved:
            entry["saved_by"] = "browser_save.mjs"
            entry["fetched_at"] = saved.get("saved_at", stamp)[:10]
            if saved.get("final_url") and saved["final_url"] != page.url:
                entry["final_url"] = saved["final_url"]
        if len(body) < MIN_PAGE_BYTES:
            entry["error"] = f"stub: {len(body)} bytes; check this page in the browser"
        entries[target.name] = entry
        registered += 1
        how = "browser-saved" if saved else "hand-saved"
        log(f"  {page.file}: registered as {how} ({len(body)} bytes)")
    _write_manifest(manifest_path, sources, entries)
    log(f"{sources.layer}: {registered} page(s) registered -> {manifest_path}")
    return registered


def run(
    sources: SourceList,
    out_dir: Path,
    *,
    fetcher: Fetcher = fetch_url,
    pause: float = DEFAULT_PAUSE_SECONDS,
    refresh: bool = False,
    today: str | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Fetch every page in `sources` into `out_dir`. Returns the number of
    pages that failed. `fetcher` is injectable so the tests never touch the
    network; `today` likewise so a manifest written in a test is stable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / MANIFEST_NAME
    entries = _read_manifest(manifest_path)
    stamp = today or date.today().isoformat()
    failed = 0
    fetched = 0
    skipped = 0
    requested = 0

    for page in sources.pages:
        target = out_dir / f"{page.file}.html"
        if target.is_file() and not refresh and target.name in entries:
            skipped += 1
            continue
        if requested and pause:
            time.sleep(pause)
        requested += 1
        entry = {
            "file": target.name,
            "url": page.url,
            "lang": page.lang,
            "program": page.program,
            "layer": sources.layer,
            "terms": sources.terms,
            "terms_checked": sources.terms_checked,
            "fetched_at": stamp,
        }
        try:
            status, body = fetcher(page.url)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            status, body = 0, b""
            entry["error"] = str(exc)
        entry["status"] = status
        if status == 200 and len(body) < MIN_PAGE_BYTES:
            entry["error"] = (
                f"stub: {len(body)} bytes with status 200, most likely a bot-challenge "
                f"page; save this one from a browser"
            )
            status = 0
        if status == 200 and body:
            target.write_bytes(body)
            entry["sha256"] = hashlib.sha256(body).hexdigest()
            entry["bytes"] = len(body)
            fetched += 1
            log(f"  {page.file}: {len(body)} bytes")
        else:
            failed += 1
            entry.setdefault("error", f"HTTP {status}" if status else "no response")
            if target.exists():
                target.unlink()
            log(f"  {page.file}: FAILED ({entry['error']})")
        entries[target.name] = entry
        # Written after every page, so an interrupted run leaves a manifest
        # that describes exactly the files on disk.
        _write_manifest(manifest_path, sources, entries)

    log(
        f"{sources.layer}: {fetched} fetched, {skipped} already present, {failed} failed "
        f"-> {out_dir}/{MANIFEST_NAME}"
    )
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a declared list of public pages into a directory, with a manifest."
    )
    parser.add_argument("sources", help="TOML source list (one corpus layer)")
    parser.add_argument("-o", "--output", required=True, help="directory to save pages into")
    parser.add_argument(
        "--refresh", action="store_true", help="re-fetch pages that are already saved"
    )
    parser.add_argument(
        "--browser-jobs",
        action="store_true",
        help=(
            "no network: write browser-jobs.json listing the pages not yet fetched, "
            "for browser_save.mjs"
        ),
    )
    parser.add_argument(
        "--hand-saved",
        action="store_true",
        help=(
            "no network: register pages saved from a browser (by a person or by "
            "browser_save.mjs) into the output directory under the derived file names"
        ),
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=DEFAULT_PAUSE_SECONDS,
        help=f"seconds between requests (default {DEFAULT_PAUSE_SECONDS})",
    )
    args = parser.parse_args(argv)
    try:
        sources = load_sources(args.sources)
    except SourceError as exc:
        print(f"fetch_pages: error: {exc}", file=sys.stderr)
        return 2
    print(
        f"Layer {sources.layer!r}: {len(sources.pages)} page(s); terms {sources.terms} "
        f"(read {sources.terms_checked})"
    )
    if args.browser_jobs:
        write_browser_jobs(sources, Path(args.output))
        return 0
    if args.hand_saved:
        register_hand_saved(sources, Path(args.output))
        return 0
    failed = run(sources, Path(args.output), pause=args.pause, refresh=args.refresh)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
