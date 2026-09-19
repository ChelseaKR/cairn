#!/usr/bin/env python3
"""Build the static evidence page from the committed evidence, and nothing else.

`site/index.html` is a committed artifact, not a service. Its one script is
the guarded Google Analytics 4 loader described at `GA4_MEASUREMENT_ID` below
(owner decision 2026-09-17); nothing else on it runs or fetches, and every
quoted string in it is copied verbatim out of a file already in this
repository:

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

`site/privacy.html` is built here too, from the constants below and nothing
else, and committed and checked the same way.

Usage:
    python3 site_build.py            # write site/index.html and site/privacy.html
    python3 site_build.py --check    # exit 1 if either committed file is stale
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "plumbline" / "bundle"
BASELINE = ROOT / "plumbline" / "baseline.json"
OUT = ROOT / "site" / "index.html"
CARD = ROOT / "site" / "og-card.png"
PROJECT = ROOT / "pyproject.toml"
PRIVACY_OUT = ROOT / "site" / "privacy.html"

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

# The name of the site as a thing, as opposed to the title of this one page.
# Named once because it is now stated in three places that a reader or a
# machine can compare: `og:site_name`, and the two structured-data nodes below.
SITE_NAME = "Cairn"

# The language the page is written in. Named once for the same reason: it is
# stated in `<html lang>` and again in the structured data, and a page that
# declares two different languages about itself has told a crawler nothing.
PAGE_LANG = "en"

# The evidence shown, in the order it is shown. The refusal leads: it is the
# behavior the project is named for, and a demonstration that opens with a
# successful answer is a demonstration of something every assistant can do.
REFUSALS = ("ck-017", "ck-024")
CROSS_LANGUAGE = "ck-027"

# Google Analytics 4, on both pages of this site (owner decision 2026-09-17:
# GA4 on every public site, with the privacy copy changed to match).
#
# The measurement ID is public -- every page that loads GA hands it to the
# browser -- so it is committed here as configuration, not kept as a secret.
# Empty ("") means the build emits no analytics at all: no <script>, no
# reference to Google, no opt-out control, and the footer and privacy page say
# the site runs none. A malformed ID fails the build instead of shipping.
#
# What the loader does, in order, on every page that carries it:
#
# - Wires the footer's "Opt out of analytics" / "Opt back in" control.
# - Returns, loading nothing, unless the page is being served from
#   GA4_HOST under GA4_PATH. The committed file is byte-for-byte the file
#   GitHub Pages serves, so the guard is at run time: a local preview
#   (file://, localhost, 127.0.0.1) or any other copy never loads GA and
#   never sends a hit to the real property.
# - Returns when navigator.globalPrivacyControl === true, when Do Not Track
#   is on (navigator.doNotTrack, window.doNotTrack or navigator.msDoNotTrack
#   is "1" or "yes"), or when the visitor opted out. No Google script, no
#   dataLayer, no request, no cookie.
# - Sets Consent Mode v2 defaults: ad_storage, ad_user_data and
#   ad_personalization denied everywhere; analytics_storage denied in the
#   EEA, the UK and Switzerland (via `region`) and granted elsewhere. There
#   is no banner, so nothing updates them: visitors in those regions get no
#   GA cookies, and gtag.js sends Google cookieless pings instead.
# - Configures gtag with allow_google_signals and
#   allow_ad_personalization_signals both false, then loads gtag.js.
GA4_MEASUREMENT_ID = "G-BJR1YH7N91"
# Must match the property's Admin > Data retention setting; privacy.html
# states it.
GA4_DATA_RETENTION = "14 months"
# Where the loader may run. GitHub Pages serves this project under a path of
# an origin its sibling projects share, so the host alone is not enough.
GA4_HOST = "chelseakr.github.io"
GA4_PATH = "/cairn/"
# The footer's opt-out, remembered per browser in localStorage. Every project
# under chelseakr.github.io shares one origin and so one localStorage; a
# generic key would opt a visitor out of every sibling site at once, so this
# one names the project. Renaming it would silently opt every opted-out
# visitor back in: never rename it.
GA4_OPT_OUT_KEY = "cairn:analytics-opt-out"

# GA4 web-stream measurement IDs are "G-" plus uppercase letters and digits.
# Checked strictly because the value is interpolated into an inline script.
MEASUREMENT_ID_RE = re.compile(r"G-[A-Z0-9]{4,20}")

# analytics_storage defaults to denied for visitors in these regions (ISO
# 3166-1 alpha-2): the 27 EU member states, the other three EEA states
# (Iceland, Liechtenstein, Norway), the United Kingdom and Switzerland.
EU_MEMBER_STATES = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
)  # fmt: skip
ANALYTICS_DENIED_REGIONS = (*EU_MEMBER_STATES, "IS", "LI", "NO", "GB", "CH")

GTAG_JS_URL = "https://www.googletagmanager.com/gtag/js"

# The footer control's status line after each change, announced through its
# role="status" live region.
OPT_OUT_MESSAGES = {
    "__MSG_OPTED_OUT__": (
        "Opted out. From the next page you open, this site will not load Google "
        "Analytics in this browser."
    ),
    "__MSG_IS_OUT__": (
        "You have opted out: this site does not load Google Analytics in this browser."
    ),
    "__MSG_BACK_IN__": "Opted back in. Analytics resumes from the next page you open.",
    "__MSG_SIGNAL__": (
        "Analytics is off: your browser sends Global Privacy Control or Do Not Track."
    ),
    "__MSG_NO_STORAGE__": (
        "This browser is blocking site storage, so an opt-out cannot be remembered "
        "here. Global Privacy Control or Do Not Track keeps analytics off."
    ),
}

GA4_TEMPLATE = r"""<script>
(function () {
  var w = window, n = navigator, d = document, KEY = __OPT_OUT_KEY__, OFF = __GA_DISABLE__;
  var store = null;
  try { store = w.localStorage; store.getItem(KEY); } catch (e) { store = null; }
  function optedOut() {
    try { return !!store && store.getItem(KEY) === "1"; } catch (e) { return false; }
  }
  var dnt = n.doNotTrack || w.doNotTrack || n.msDoNotTrack;
  var signal = n.globalPrivacyControl === true || dnt === "1" || dnt === "yes";
  d.addEventListener("DOMContentLoaded", function () {
    var box = d.querySelector("[data-analytics-choice]");
    if (!box) return;
    var button = box.querySelector("button"), status = box.querySelector("[role=status]");
    function render(message) {
      button.textContent = optedOut() ? "Opt back in" : "Opt out of analytics";
      button.hidden = signal || !store;
      status.textContent = message;
      box.hidden = false;
    }
    button.addEventListener("click", function () {
      try {
        if (optedOut()) {
          store.removeItem(KEY);
          w[OFF] = false;
          render(__MSG_BACK_IN__);
        } else {
          store.setItem(KEY, "1");
          w[OFF] = true;
          render(__MSG_OPTED_OUT__);
        }
      } catch (e) {
        store = null;
        render(__MSG_NO_STORAGE__);
      }
    });
    render(signal ? __MSG_SIGNAL__ : !store ? __MSG_NO_STORAGE__
      : optedOut() ? __MSG_IS_OUT__ : "");
  });
  if (w.location.hostname !== __HOST__) return;
  if (w.location.pathname.indexOf(__PATH__) !== 0) return;
  if (n.globalPrivacyControl === true) return;
  if (dnt === "1" || dnt === "yes") return;
  if (optedOut()) return;
  w.dataLayer = w.dataLayer || [];
  function gtag() { w.dataLayer.push(arguments); }
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "denied", region: __DENIED_REGIONS__
  });
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "granted"
  });
  gtag("js", new Date());
  gtag("config", __ID__, {
    allow_google_signals: false, allow_ad_personalization_signals: false
  });
  var s = d.createElement("script");
  s.async = true;
  s.src = __GTAG_SRC__;
  d.head.appendChild(s);
})();
</script>
"""


def measurement_id(value: str | None) -> str | None:
    """None for an unset or blank ID, the ID itself when well formed.

    Anything else raises rather than being interpolated into a script: a typo
    should fail the build, not publish a broken tag.
    """
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not MEASUREMENT_ID_RE.fullmatch(value):
        raise ValueError(f"not a GA4 measurement ID (expected G-XXXXXXXXXX): {value!r}")
    return value


def ga4_snippet(ga4_id: str | None) -> str:
    """The loader for one page's <head>: "" when no ID is set."""
    mid = measurement_id(ga4_id)
    if mid is None:
        return ""
    replacements = {
        "__OPT_OUT_KEY__": json.dumps(GA4_OPT_OUT_KEY),
        "__GA_DISABLE__": json.dumps(f"ga-disable-{mid}"),
        "__HOST__": json.dumps(GA4_HOST),
        "__PATH__": json.dumps(GA4_PATH),
        "__DENIED_REGIONS__": json.dumps(list(ANALYTICS_DENIED_REGIONS)),
        "__ID__": json.dumps(mid),
        "__GTAG_SRC__": json.dumps(f"{GTAG_JS_URL}?id={mid}"),
        **{token: json.dumps(message) for token, message in OPT_OUT_MESSAGES.items()},
    }
    snippet = GA4_TEMPLATE
    for token, value in replacements.items():
        snippet = snippet.replace(token, value)
    return snippet


def privacy_footer(ga4_id: str | None) -> str:
    """The footer's privacy line, true for the build it is in."""
    if measurement_id(ga4_id) is None:
        return (
            '  <p class="privacy-note">This site runs no analytics and sets no cookies. '
            '<a href="privacy.html">Privacy</a>.</p>\n'
        )
    return (
        '  <p class="privacy-note">This site counts visits with Google Analytics 4, '
        "advertising features off, and does not load it when your browser sends Global "
        'Privacy Control or Do Not Track. <a href="privacy.html">Privacy</a>.\n'
        '  <span data-analytics-choice hidden><button type="button" class="link-button">'
        'Opt out of analytics</button> <span role="status"></span></span></p>\n'
    )


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



def png_dimensions(path: Path) -> tuple[int, int]:
    """The card's width and height, read out of the PNG's own IHDR chunk.

    The head states the card's size so a preview consumer can reserve space
    before the image arrives. Those two numbers used to be typed into the
    template, which made them a claim *about* a file rather than a reading
    *of* it: re-render the card at another size and the page would go on
    announcing the old one. `tests/test_site.py` did catch that, but caught it
    as a failing test asking a human to retype a number -- and a number a
    human maintains by hand next to a file that already knows it is the shape
    this repository keeps taking out. Reading the file is the same check with
    nothing left to keep in sync.

    IHDR is the first chunk of every PNG and its width and height are
    big-endian 32-bit fields at fixed offsets 16 and 20.
    """
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path} is not a PNG, so the head cannot state its size")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def project_metadata() -> dict:
    """The `[project]` table of `pyproject.toml`.

    The packaging metadata is where this project already says what it is and
    where it lives, for the benefit of the PyPI page. Restating any of it here
    would be a second copy nobody diffs against the first, so the structured
    data reads it instead.
    """
    return tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]


def structured_data(card_width: int, card_height: int) -> str:
    """A schema.org description of what this page is and what it is about.

    Every value is read back out of the same constants and files that render
    the visible head, so the machine-readable claim and the human-readable one
    cannot disagree: the node's `name` is the `<title>`, its `description` is
    the `<meta name=description>`, its `url` is the canonical, and the image's
    dimensions are the ones read off the committed PNG.

    What is deliberately absent is as much the point as what is here. There is
    no `Dataset` node and no DCAT vocabulary. A dataset descriptor exists to be
    harvested -- it asks dataset search engines and open-data catalogs to list
    the thing it describes, and a catalog listing is hard to withdraw once
    taken. Whether this portfolio wants to invite that is an open question with
    an owner's name on it, and it is not answered by adding the markup quietly.
    Saying "this page is about a piece of software" answers nothing of the sort
    and needs no such decision, so that is all this says.

    No `softwareVersion` either, though `pyproject.toml` has one. `site/index.html`
    is a committed artifact checked for staleness, so binding it to the package
    version would make every release a version bump *and* a page regeneration,
    with a red build in between. That is a real cost for a field no reader of
    this page is looking for.
    """
    project = project_metadata()
    urls = project["urls"]
    page = SITE_URL
    website_id = page + "#website"
    image_id = CARD_URL
    software_id = urls["Repository"] + "#software"

    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": website_id,
                "url": page,
                "name": SITE_NAME,
                "inLanguage": PAGE_LANG,
            },
            {
                "@type": "WebPage",
                "@id": page + "#webpage",
                "url": page,
                "name": PAGE_TITLE,
                "description": PAGE_DESCRIPTION,
                "inLanguage": PAGE_LANG,
                "isPartOf": {"@id": website_id},
                "primaryImageOfPage": {"@id": image_id},
                "about": {"@id": software_id},
            },
            {
                "@type": "ImageObject",
                "@id": image_id,
                "url": CARD_URL,
                "width": card_width,
                "height": card_height,
                "caption": CARD_ALT,
            },
            {
                "@type": "SoftwareApplication",
                "@id": software_id,
                "name": SITE_NAME,
                "alternateName": project["name"],
                "description": project["description"],
                "url": page,
                "sameAs": urls["Repository"],
                "inLanguage": PAGE_LANG,
            },
        ],
    }
    return block_body(payload)


def block_body(payload: object) -> str:
    """Serialize `payload` as an element body that cannot end its own element.

    `</script` inside a JSON string ends the element as far as an HTML parser
    is concerned, whatever JSON thinks. Escaping the three characters that can
    start markup keeps the block inert without changing what it decodes to,
    which is what every consumer of this actually reads.

    Split out of the caller so a test can hand it a value that needs escaping.
    Nothing in this page's title, description or packaging metadata contains
    any of the three today, so deleting the escaping below changes no byte of
    the real output and no other check here would notice.
    """
    return (
        json.dumps(payload, ensure_ascii=False, indent=2)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


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
    li { margin: .4rem 0; }
    /* The footer's analytics opt-out changes a setting rather than going
       anywhere, so it is a button, drawn like the links around it. */
    .link-button {
      font: inherit; color: var(--accent); background: none; border: 0; padding: 0;
      text-decoration: underline; cursor: pointer;
    }
"""


def render(ga4_id: str | None = GA4_MEASUREMENT_ID) -> str:
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

    card_width, card_height = png_dimensions(CARD)
    ld_json = structured_data(card_width, card_height)

    return f"""<!DOCTYPE html>
<html lang="{PAGE_LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(PAGE_TITLE)}</title>
<meta name="description" content="{esc(PAGE_DESCRIPTION)}">
<link rel="canonical" href="{esc(SITE_URL)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:url" content="{esc(SITE_URL)}">
<meta property="og:title" content="{esc(PAGE_TITLE)}">
<meta property="og:description" content="{esc(PAGE_DESCRIPTION)}">
<meta property="og:image" content="{esc(CARD_URL)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="{card_width}">
<meta property="og:image:height" content="{card_height}">
<meta property="og:image:alt" content="{esc(CARD_ALT)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{esc(CARD_URL)}">
<meta name="twitter:image:alt" content="{esc(CARD_ALT)}">
<script type="application/ld+json">
{ld_json}
</script>
{ga4_snippet(ga4_id)}<style>{STYLE}</style>
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
  <p>The interesting behavior of a grounded assistant is the one it declines to
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
  This is a demonstration of correct behavior, not a public service.</p>
  <p>This page is a committed file, built by
  <a href="{REPO}/blob/main/site_build.py"><code>site_build.py</code></a> and held
  against the evidence by
  <a href="{REPO}/blob/main/tests/test_site.py"><code>tests/test_site.py</code></a>,
  which parses this HTML and compares what it finds to the JSONL. If they ever
  disagree, the build fails rather than the page drifting.
  Source: <a href="{REPO}">github.com/ChelseaKR/cairn</a>.</p>
{privacy_footer(ga4_id)}</footer>
</body>
</html>
"""


def privacy_body(ga4_id: str | None) -> str:
    """What the privacy page says, which depends on whether the build has an ID."""
    hosting = (
        "  <h2>Hosting</h2>\n"
        "  <p>GitHub Pages serves this site. Like any web host, GitHub receives each "
        "request, including your IP address; see the "
        '<a href="https://docs.github.com/en/site-policy/privacy-policies/'
        'github-general-privacy-statement">GitHub General Privacy Statement</a>.</p>\n'
    )
    tool = (
        "  <p>This page is about this website only. The Cairn software itself has no "
        "telemetry: it reports nothing about its use to anyone, and it answers from a "
        "local corpus with no network at answer time.</p>\n"
    )
    if measurement_id(ga4_id) is None:
        return (
            "  <p>This site runs no analytics, loads no third-party script and sets "
            "no cookies.</p>\n" + tool + hosting
        )
    return f"""  <p>This site, the evidence page and this page, counts visits with Google
  Analytics 4, a service of Google LLC in the United States. Nothing else on it
  tracks you.</p>
{tool}
  <h2>What Google Analytics records</h2>
  <p>For each page you open: the page address and the page you came from, the
  time, your browser, device and screen size, your language, and a rough
  location that Google works out from your IP address. Google Analytics 4 does
  not store the IP address itself. By default it also records scrolling and
  clicks on links that leave this site.</p>

  <h2>Cookies</h2>
  <p>Outside the places listed below, Google Analytics sets two cookies on
  chelseakr.github.io, named <code>_ga</code> and <code>_ga_</code> followed by
  an ID. They let it tell a returning browser from a new one, and last up to two
  years. In the European Economic Area, the United Kingdom and Switzerland it
  sets no analytics cookies. There, Google still receives a cookieless ping for
  each page.</p>

  <h2>Advertising features are off</h2>
  <p>Google signals and ad personalization are both turned off, and the
  advertising storage, ad user data and ad personalization consent signals are
  denied everywhere. Google keeps the event data for
  {esc(GA4_DATA_RETENTION)}. See
  <a href="https://policies.google.com/privacy">Google's privacy policy</a>.</p>

  <h2 id="opt-out">Opting out</h2>
  <ul>
    <li><strong>On this device:</strong> use &ldquo;Opt out of analytics&rdquo;
    at the bottom of any page. It stores <code>{esc(GA4_OPT_OUT_KEY)}</code> in
    this browser's local storage and sends it nowhere. From then on this site
    does not load Google Analytics in this browser. The same button then reads
    &ldquo;Opt back in&rdquo;, which removes the setting.</li>
    <li><strong>In any browser:</strong> turn on Global Privacy Control or Do Not
    Track. This site then never loads Google Analytics at all.</li>
    <li>Or install
    <a href="https://tools.google.com/dlpage/gaoptout">Google's Analytics opt-out
    browser add-on</a>.</li>
  </ul>
{hosting}"""


def render_privacy(ga4_id: str | None = GA4_MEASUREMENT_ID) -> str:
    """`site/privacy.html`: what this site collects, true for the build it is in."""
    title = "Cairn — privacy"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="What this site collects about visitors, and how to opt out.">
<link rel="canonical" href="{esc(SITE_URL)}privacy.html">
{ga4_snippet(ga4_id)}<style>{STYLE}</style>
</head>
<body>
<main>
  <h1>Privacy</h1>
{privacy_body(ga4_id)}  <p><a href="./">Back to the evidence page</a>.</p>
</main>
<footer>
{privacy_footer(ga4_id)}</footer>
</body>
</html>
"""


def pages(ga4_id: str | None = GA4_MEASUREMENT_ID) -> dict[Path, str]:
    """Every committed page this script owns, and what it renders to."""
    return {OUT: render(ga4_id), PRIVACY_OUT: render_privacy(ga4_id)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if a committed page is not what this would write",
    )
    args = parser.parse_args(argv)
    rendered = pages()
    if args.check:
        stale = 0
        for out, page in rendered.items():
            if not out.is_file():
                print(f"{out} does not exist; run `python3 site_build.py`", file=sys.stderr)
                stale += 1
            elif out.read_text(encoding="utf-8") != page:
                print(
                    f"{out} is not what the committed evidence renders to. The evidence "
                    f"changed and the page did not. Run `python3 site_build.py`.",
                    file=sys.stderr,
                )
                stale += 1
            else:
                print(f"{out} is current")
        return 1 if stale else 0
    for out, page in rendered.items():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
