#!/usr/bin/env python3
"""Build the static evidence page from the committed evidence, and nothing else.

`site/index.html` is a committed artifact, not a service. It holds no
JavaScript, fetches nothing, and every quoted string in it is copied verbatim
out of a file already in this repository:

    plumbline/bundle/items.jsonl      what was asked
    plumbline/bundle/responses.jsonl  what Cairn replied
    plumbline/bundle/checksums.json   the dataset id those two hash to
    plumbline/baseline.json           what the pinned auditor scored them

Committed rather than generated at deploy time on purpose. A page built inside
the deploy is a page nobody reviewed; committing it puts every change to what
the site says in a diff, next to the change to the evidence it says it about.
The deploy workflow uploads the file and does not run this script.

**This script is not the check.** Re-running a generator and diffing its output
proves the file is not hand-edited and not stale; it cannot prove the generator
copies the evidence rather than inventing it, because the generator is what
produced both sides. `tests/test_site.py` does that half — it parses the
committed HTML with a parser that has never seen this file and holds the text
it finds against the JSONL. Both checks run in the offline test suite, so the
merge gate covers them and the deploy cannot be the first place a drift is
noticed.

Usage:
    python3 site_build.py            # write site/index.html
    python3 site_build.py --check    # exit 1 if the committed file is stale
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "plumbline" / "bundle"
BASELINE = ROOT / "plumbline" / "baseline.json"
OUT = ROOT / "site" / "index.html"

REPO = "https://github.com/ChelseaKR/cairn"

# Where this page is served from, in full, including the project path.
#
# GitHub Pages serves this repository at a path under a shared origin, not at
# an origin of its own: five sibling projects are published under
# chelseakr.github.io as well, and https://chelseakr.github.io/ itself is a
# 404. So every absolute reference here carries `/cairn/`. A root-relative
# `/index.html` or a canonical naming the bare origin would not point at a
# different page of this site, it would point at somebody else's project or at
# nothing, and it would tell a crawler that six separate sites are one site.
# tests/test_site.py holds this to the project path for that reason.
SITE_URL = "https://chelseakr.github.io/cairn/"

# The page's title and description, named once and used by both the plain tags
# and the Open Graph ones. Two copies of a sentence are two things that can
# drift, and a share card that describes a page differently from the page is
# the same defect this repository exists to complain about.
PAGE_TITLE = "Cairn — recorded evidence"
PAGE_DESCRIPTION = (
    "Recorded answers, refusals and audit scores from Cairn, a "
    "grounded-or-silent reference assistant for public agencies."
)

# The share image, and the same reasoning as SITE_URL: absolute, and carrying
# the project path. Every consumer of `og:image` — Slack, Signal, Mastodon, the
# search crawlers — fetches it from its own machine with no page context, so a
# relative `og-card.png` resolves against whatever they think the base is, and a
# root-relative one resolves to a sibling project's site.
#
# `site/og-card.png` is committed next to the page and uploaded with it by the
# pages workflow, which publishes the whole `site` directory. It renders the two
# constants above and nothing else, so the card a link preview shows and the
# text the page carries are the same sentence rather than two that can drift.
CARD_URL = SITE_URL + "og-card.png"
CARD_ALT = (
    "Cairn — recorded evidence. " + PAGE_DESCRIPTION.rstrip(".") + "."
)

# The evidence shown, in the order it is shown. The refusal leads: it is the
# behaviour the project is named for, and a demonstration that opens with a
# successful answer is a demonstration of something every assistant can do.
REFUSALS = ("ck-017", "ck-024")
CROSS_LANGUAGE = "ck-027"


def jsonl(path: Path) -> dict[str, dict]:
    return {
        json.loads(line)["id"]: json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def direction(lang: str) -> str:
    return "rtl" if lang == "ar" else "ltr"


def exchange(item: dict, response: str, *, note: str = "") -> str:
    """One question and one answer, marked up so a parser can find both.

    `data-evidence` marks a leaf whose text must equal a value in the bundle;
    `data-exchange` marks the article around a pair of them, which is how the
    check knows what order the page presents them in. The attributes are the
    contract between the page and `tests/test_site.py`; renaming one without
    renaming the other fails the check rather than silently emptying it.
    """
    lang, dir_ = item["lang"], direction(item["lang"])
    sources = item.get("sources") or []
    if sources:
        cited = (
            "<p class=\"sources\">Cited: "
            + ", ".join(f"<code>{esc(s)}</code>" for s in sources)
            + "</p>"
        )
    else:
        cited = '<p class="sources no-sources">No sources. Nothing was cited '
        cited += "because nothing was grounded.</p>"
    ident = esc(item["id"])
    return (
        f'      <article class="exchange" data-exchange="{ident}">\n'
        f"        <h3>\n"
        f'          <span class="item-id">{ident}</span>\n'
        f'          <span class="behavior">{esc(item["behavior"])}</span>\n'
        f'          <span class="lang-tag">asked in {esc(lang)}</span>\n'
        f"        </h3>\n"
        f'        <p class="label" id="q-{ident}">Question</p>\n'
        f'        <blockquote class="prompt" data-evidence="prompt" data-item="{ident}"\n'
        f'          lang="{esc(lang)}" dir="{dir_}" aria-labelledby="q-{ident}"'
        f">{esc(item['prompt'])}</blockquote>\n"
        f'        <p class="label" id="a-{ident}">What Cairn replied</p>\n'
        f'        <pre class="response" data-evidence="response" data-item="{ident}"\n'
        f'          lang="{esc(lang)}" dir="{dir_}" aria-labelledby="a-{ident}"'
        f">{esc(response)}</pre>\n"
        f"        {cited}\n"
        f"{note}      </article>\n"
    )


def suite_rows(baseline: dict) -> str:
    rows = []
    for entry in baseline["suites"]:
        rows.append(
            f'          <tr data-evidence="suite" data-suite="{esc(entry["suite"])}">\n'
            f'            <th scope="row">{esc(entry["suite"])}</th>\n'
            f'            <td data-field="score">{entry["score"]:.4f}</td>\n'
            f'            <td data-field="floor">{entry["floor"]:.2f}</td>\n'
            f'            <td data-field="n">{entry["n"]}</td>\n'
            f'            <td data-field="verdict">{esc(entry["verdict"])}</td>\n'
            f"          </tr>"
        )
    return "\n".join(rows)


STYLE = """
    :root {
      color-scheme: light dark;
      --bg: #ffffff;
      --fg: #16191d;
      --muted: #4d545c;
      --rule: #c9ced4;
      --panel: #f4f6f8;
      --accent: #1f4f8f;
      --warn: #8a3a12;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #14171a;
        --fg: #e9ecef;
        --muted: #aeb6bf;
        --rule: #3a4149;
        --panel: #1d2126;
        --accent: #8fb8ee;
        --warn: #f0a878;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0 auto; padding: 2rem 1.25rem 4rem; max-width: 46rem;
      background: var(--bg); color: var(--fg);
      font: 1rem/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    h1 { font-size: 1.75rem; line-height: 1.25; margin: 0 0 .25rem; }
    h2 { font-size: 1.2rem; margin: 2.75rem 0 .5rem; }
    h3 {
      font-size: .8rem; font-weight: 600; margin: 0 0 .75rem;
      display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline;
    }
    a { color: var(--accent); }
    .tagline { color: var(--muted); margin: 0 0 1.5rem; }
    .exchange {
      border: 1px solid var(--rule); border-radius: 8px;
      padding: 1rem 1.15rem; margin: 1rem 0; background: var(--panel);
    }
    .item-id { font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; }
    .behavior, .lang-tag {
      font-weight: 400; color: var(--muted);
      border: 1px solid var(--rule); border-radius: 999px; padding: .05rem .5rem;
    }
    .label {
      font-size: .75rem; text-transform: uppercase; letter-spacing: .06em;
      color: var(--muted); margin: .9rem 0 .3rem;
    }
    blockquote.prompt {
      margin: 0; padding: 0 0 0 .85rem; border-inline-start: 3px solid var(--accent);
      font-size: 1.05rem;
    }
    pre.response {
      margin: 0; padding: .75rem .85rem; overflow-x: auto;
      background: var(--bg); border: 1px solid var(--rule); border-radius: 6px;
      font: .9rem/1.55 ui-monospace, "SFMono-Regular", Menlo, monospace;
      white-space: pre-wrap; word-break: break-word;
    }
    .sources { font-size: .85rem; color: var(--muted); margin: .75rem 0 0; }
    .no-sources { color: var(--warn); }
    .aside {
      font-size: .92rem; margin: .9rem 0 0; padding-top: .8rem;
      border-top: 1px dashed var(--rule); color: var(--muted);
    }
    table { border-collapse: collapse; width: 100%; font-size: .9rem; }
    caption { text-align: start; color: var(--muted); padding-bottom: .5rem; }
    th, td { text-align: start; padding: .3rem .55rem; border-bottom: 1px solid var(--rule); }
    td { font-variant-numeric: tabular-nums; }
    code { font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; font-size: .9em; }
    footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rule);
             font-size: .87rem; color: var(--muted); }
"""


def render() -> str:
    items = jsonl(BUNDLE / "items.jsonl")
    responses = {k: v["response"] for k, v in jsonl(BUNDLE / "responses.jsonl").items()}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    checksums = json.loads((BUNDLE / "checksums.json").read_text(encoding="utf-8"))
    dataset_id = checksums["bundle_sha256"][:12]

    multilingual = next(s for s in baseline["suites"] if s["suite"] == "multilingual")
    passed = round(multilingual["score"] * multilingual["n"])

    refusals = "".join(exchange(items[i], responses[i]) for i in REFUSALS)

    cross_note = (
        f'        <p class="aside">Asked in Arabic. The only source Cairn has is the '
        f"English transit document, so it says so in Arabic and then quotes the English "
        f"exactly as published — translating a policy sentence would produce a number "
        f"no source contains. Its own auditor scores that a failure: the "
        f"<code>multilingual</code> suite asks whether a person who wrote in Arabic got "
        f"Arabic back, and the body of this answer is English. "
        f"{passed} of {multilingual['n']} items pass it, and the one that does not is "
        f"this one. Both positions are correct and the number is still zero; the "
        f"reasoning, and why the floor was not lowered to make it go away, is in "
        f'<a href="{REPO}/blob/main/DESIGN.md">DESIGN.md</a>.</p>\n'
    )
    cross = exchange(items[CROSS_LANGUAGE], responses[CROSS_LANGUAGE], note=cross_note)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(PAGE_TITLE)}</title>
<meta name="description" content="{esc(PAGE_DESCRIPTION)}">
<link rel="canonical" href="{esc(SITE_URL)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Cairn">
<meta property="og:url" content="{esc(SITE_URL)}">
<meta property="og:title" content="{esc(PAGE_TITLE)}">
<meta property="og:description" content="{esc(PAGE_DESCRIPTION)}">
<meta property="og:image" content="{esc(CARD_URL)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{esc(CARD_ALT)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{esc(CARD_URL)}">
<meta name="twitter:image:alt" content="{esc(CARD_ALT)}">
<style>{STYLE}</style>
</head>
<body>
<main>
  <h1>Cairn: what it actually did</h1>
  <p class="tagline">A reference implementation of a reference assistant for public
  agencies. It answers only from a corpus an operator supplies, cites every answer,
  and refuses when it cannot ground one. Everything below is copied verbatim out of
  the evidence bundle committed at
  <a href="{REPO}/tree/main/plumbline/bundle"><code>plumbline/bundle</code></a> —
  not re-run, not re-typed, and checked against those files by the test suite.</p>

  <h2>It refuses</h2>
  <p>The interesting behaviour of a grounded assistant is the one it declines to
  perform. Neither question below is covered by the corpus, so neither gets an
  answer, and the refusal points at a person instead of guessing.</p>
{refusals}
  <h2>It will not translate a source to make an answer look better</h2>
{cross}
  <h2>What the audit made of all 27</h2>
  <p>Scored by <a href="https://github.com/ChelseaKR/plumbline">Plumbline</a>, pinned
  to an exact commit, against dataset
  <code data-evidence="dataset-id">{esc(dataset_id)}</code> — the SHA-256 of the
  bundle above, so this table cannot be about a different set of answers than the
  ones on this page.</p>
  <table>
    <caption>Committed baseline. A floor is a minimum; the repository additionally
    fails on any score that moves against this table in either direction.</caption>
    <thead>
      <tr><th scope="col">Suite</th><th scope="col">Score</th><th scope="col">Floor</th>
      <th scope="col">n</th><th scope="col">Verdict</th></tr>
    </thead>
    <tbody>
{suite_rows(baseline)}
    </tbody>
  </table>
</main>
<footer>
  <p><strong>The corpus is invented.</strong> Every document Cairn answers from here is
  synthetic demonstration content, and the contact number in the refusals is fictional.
  This is a demonstration of correct behaviour, not a public service.</p>
  <p>This page is a committed file, built by
  <a href="{REPO}/blob/main/site_build.py"><code>site_build.py</code></a> and held
  against the evidence by
  <a href="{REPO}/blob/main/tests/test_site.py"><code>tests/test_site.py</code></a>,
  which parses this HTML and compares what it finds to the JSONL. If they ever
  disagree, the build fails rather than the page drifting.
  Source: <a href="{REPO}">github.com/ChelseaKR/cairn</a>.</p>
</footer>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed page is not what this would write",
    )
    args = parser.parse_args(argv)
    page = render()
    if args.check:
        if not OUT.is_file():
            print(f"{OUT} does not exist; run `python3 site_build.py`", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != page:
            print(
                f"{OUT} is not what the committed evidence renders to. The evidence "
                f"changed and the page did not. Run `python3 site_build.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT} is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
