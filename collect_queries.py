"""Real questions, from people who were never asked: search queries and
public Q&A, filtered to the pilot's programs.

Dev-only, stdlib-only, not part of the runtime. The pilot (`docs/pilot-ca.md`)
needs questions nobody wrote for Cairn, in the words people actually use.
The first plan was to ask eight to twelve people; that needs eight to twelve
people. This script draws from two public sources instead, and says what
each one is and is not.

**MS MARCO queries** (`--msmarco`): about a million real, anonymised Bing
search queries released by Microsoft for non-commercial research. Filtered
by the vocabulary of the pilot's programs, they are the closest thing there
is to a person typing a question into a box: "how long does it take to get
food stamps", "what is the income guideline for wic", "ages to collect
social security benefits". What they are not: Californian (they are
nationwide, and a query about Michigan's tax refund is a *refusal* case for
a California corpus, which is also data), recent (the collection dates from
2016–2018, so a query naming a year is naming that year), or attributable
to a county. The dataset's terms: "intended for non-commercial research
purposes only"; the selection committed here is a few hundred queries for
exactly that, with this attribution. Source:
https://microsoft.github.io/msmarco/ — `queries.tar.gz` from the passage-
ranking release, fetched into a local directory by `--download`.

**Stack Exchange** (`--stackexchange`): questions from money.stackexchange
and law.stackexchange matching the same vocabulary, via the public API.
Licensed CC BY-SA 4.0, which requires attribution: every item carries the
question's URL and the asker's display name. What they are not: typical —
people who post there are more financially literate than the median caller
to a county office, and the questions are longer and more formal.

What it writes: a TOML file of *candidates*, one `[[item]]` per question
with `prompt`, `source`, `topic`, the attribution, and **no** `behavior` or
`answering_sources`. `cairn record` refuses it as it stands, and should: a
candidate becomes an evidence item when a person reads the corpus and
labels it (`docs/pilot-ca.md`, "The question set"). The draw is
deterministic for a given seed and input, so a re-run is a diff.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode

MSMARCO_URL = "https://msmarco.z22.web.core.windows.net/msmarcoranking/queries.tar.gz"
MSMARCO_FILES = ("queries.train.tsv", "queries.dev.tsv", "queries.eval.tsv")
USER_AGENT = "cairn-pilot-collect/0.1 (+https://github.com/ChelseaKR/cairn)"
STACKEXCHANGE_API = "https://api.stackexchange.com/2.3/search/advanced"
MSMARCO_ATTRIBUTION = "MS MARCO (Microsoft), passage-ranking queries; non-commercial research"

# Topic -> the words a query has to contain. Program names in the words a
# person uses, not the agency's: "food stamps" is the term, "SNAP" the
# abbreviation, "CalFresh" the state's name for it, and all three count.
TOPICS: dict[str, str] = {
    "food": r"\b(food stamps?|snap benefits?|ebt card|calfresh|wic)\b",
    "health": r"\b(medicaid|medi-?cal|medicare|covered california)\b",
    "cash-work": (
        r"\b(ssi|ssdi|social security|unemployment (benefits?|insurance|claim|check)|"
        r"disability (benefits?|pay|insurance|check)|calworks|tanf|welfare|"
        r"general assistance|paid family leave)\b"
    ),
    "tax": (
        r"\b(eitc|earned income (tax )?credit|child tax credit|standard deduction|"
        r"tax refund|file (my |your )?taxes|payment plan with the irs|irs payment plan)\b"
    ),
    "dmv": r"\b(dmv|driver'?s? licen[cs]e|real id|car registration|vehicle registration)\b",
    "immigration": r"\b(green card|naturalization|citizenship|uscis|n-400|i-485)\b",
    "bills": (
        r"\b(liheap|lifeline|section 8|housing voucher|energy assistance|"
        r"rent(al)? assistance)\b"
    ),
    "records": (
        r"\b(register to vote|voter registration|birth certificate|small claims|"
        r"fee waiver|dog licen[cs]e)\b"
    ),
}
CALIFORNIA = r"\b(california|san mateo|sonoma|siskiyou)\b"
OTHER_STATES = (
    "alabama alaska arizona arkansas colorado connecticut delaware florida georgia hawaii "
    "idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
    "michigan minnesota mississippi missouri montana nebraska nevada new hampshire new jersey "
    "new mexico new york north carolina north dakota ohio oklahoma oregon pennsylvania "
    "rhode island south carolina south dakota tennessee texas utah vermont virginia "
    "washington west virginia wisconsin wyoming"
).split()
_TWO_WORD_STATES = (
    "new jersey|new york|new mexico|north carolina|south carolina|north dakota|"
    "south dakota|new hampshire|rhode island|west virginia"
)
_OTHER_STATE = re.compile(
    r"\b("
    + "|".join(re.escape(s) for s in OTHER_STATES if len(s) > 4)
    + "|"
    + _TWO_WORD_STATES
    + r")\b"
)


def topics_of(text: str) -> list[str]:
    lowered = text.lower()
    return [topic for topic, pattern in TOPICS.items() if re.search(pattern, lowered)]


def download_msmarco(into: Path, *, log=print) -> Path:
    """Fetch the query tarball once and unpack the three TSVs."""
    into.mkdir(parents=True, exist_ok=True)
    if all((into / name).is_file() for name in MSMARCO_FILES):
        log(f"MS MARCO queries already present in {into}")
        return into
    log(f"Downloading {MSMARCO_URL} (about 18 MB) ...")
    request = urllib.request.Request(MSMARCO_URL, headers={"User-Agent": USER_AGENT})
    # Fixed, hard-coded https URL; nothing here is caller-controlled.
    # nosemgrep: dynamic-urllib-use-detected
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name).name
            if name in MSMARCO_FILES and member.isfile():
                extracted = archive.extractfile(member)
                assert extracted is not None
                (into / name).write_bytes(extracted.read())
    log(f"Unpacked {', '.join(MSMARCO_FILES)} into {into}")
    return into


def read_msmarco(directory: Path) -> list[str]:
    queries: list[str] = []
    for name in MSMARCO_FILES:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"{path}: run with --download first")
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                _qid, _tab, query = line.rstrip("\n").partition("\t")
                if query:
                    queries.append(query)
    return queries


def select_msmarco(
    queries: list[str], *, per_topic: int, seed: int, min_words: int = 3
) -> list[dict]:
    """Deterministic stratified draw: `per_topic` queries per topic, plus
    every query that names California and a program. Duplicates (after
    case-folding and whitespace) are kept once."""
    seen: set[str] = set()
    by_topic: dict[str, list[str]] = defaultdict(list)
    california: list[str] = []
    for query in queries:
        key = " ".join(query.lower().split())
        if key in seen or len(key.split()) < min_words:
            continue
        topics = topics_of(query)
        if not topics:
            continue
        seen.add(key)
        if re.search(CALIFORNIA, key):
            california.append(query)
        else:
            by_topic[topics[0]].append(query)
    rng = random.Random(seed)
    chosen: list[tuple[str, str]] = [(q, "california") for q in sorted(california)]
    for topic in TOPICS:
        pool = sorted(by_topic.get(topic, []))
        chosen.extend((q, topic) for q in rng.sample(pool, min(per_topic, len(pool))))
    items = []
    for query, bucket in chosen:
        items.append(
            {
                "prompt": query,
                "source": "search-query",
                "topic": topics_of(query)[0],
                "names_california": bucket == "california",
                "names_other_state": bool(_OTHER_STATE.search(query.lower())),
                "attribution": MSMARCO_ATTRIBUTION,
            }
        )
    return items


def fetch_stackexchange(
    *, sites: tuple[str, ...], per_query: int, log=print, fetch=None
) -> list[dict]:
    """Top-voted questions matching each topic's key phrases, with the
    attribution CC BY-SA requires. `fetch` is injectable for tests."""
    phrases = {
        "food": ["food stamps", "calfresh", "wic"],
        "health": ["medicaid", "medi-cal", "medicare part b"],
        "cash-work": [
            "ssi", "social security benefits", "unemployment benefits", "disability benefits"
        ],
        "tax": ["earned income credit", "child tax credit", "standard deduction", "tax refund"],
        "dmv": ["driver's license", "real id", "vehicle registration"],
        "immigration": ["green card", "naturalization", "uscis fee"],
        "bills": ["section 8", "lifeline", "energy assistance"],
        "records": ["small claims", "birth certificate", "fee waiver"],
    }

    def default_fetch(url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # URL is built from a fixed https host and url-encoded parameters.
        # nosemgrep: dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            import gzip

            raw = gzip.decompress(raw)
        return json.loads(raw)

    fetch = fetch or default_fetch
    items: list[dict] = []
    seen: set[int] = set()
    for site in sites:
        for topic, terms in phrases.items():
            for term in terms:
                params = urlencode(
                    {
                        "order": "desc",
                        "sort": "votes",
                        "q": term,
                        "site": site,
                        "pagesize": per_query,
                        "filter": "default",
                    }
                )
                data = fetch(f"{STACKEXCHANGE_API}?{params}")
                for question in data.get("items", []):
                    qid = question["question_id"]
                    if qid in seen:
                        continue
                    seen.add(qid)
                    title = _unescape(question["title"])
                    items.append(
                        {
                            "prompt": title,
                            "source": "stackexchange",
                            "topic": (topics_of(title) or [topic])[0],
                            "names_california": bool(re.search(CALIFORNIA, title.lower())),
                            "names_other_state": bool(_OTHER_STATE.search(title.lower())),
                            "attribution": (
                                f"{question['link']} by "
                                f"{question['owner'].get('display_name', 'unknown')}, "
                                f"CC BY-SA 4.0"
                            ),
                        }
                    )
                if data.get("quota_remaining", 1) < 5:
                    log(f"stackexchange: quota nearly exhausted; stopping at {len(items)}")
                    return items
    return items


def _unescape(text: str) -> str:
    import html

    return html.unescape(text)


def _toml_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(items: list[dict], *, header: str) -> str:
    lines = [header.rstrip("\n"), ""]
    for index, item in enumerate(items, start=1):
        lines.append("[[item]]")
        lines.append(f'id = "cand-{index:03d}"')
        lines.append(f"prompt = {_toml_string(item['prompt'])}")
        lines.append(f"source = {_toml_string(item['source'])}")
        lines.append(f"topic = {_toml_string(item['topic'])}")
        lines.append(f"names_california = {'true' if item['names_california'] else 'false'}")
        lines.append(f"names_other_state = {'true' if item['names_other_state'] else 'false'}")
        lines.append(f"attribution = {_toml_string(item['attribution'])}")
        lines.append("# lang / behavior / answering_sources / expected / jurisdiction /")
        lines.append("# location_dependent: added by a person who has read the corpus.")
        lines.append("")
    return "\n".join(lines)


HEADER = """# Candidate questions for the real-corpus pilot — NOT an evidence set.
#
# Written by collect_queries.py from public sources of questions nobody wrote
# for Cairn. Every item here is missing `lang`, `behavior` and
# `answering_sources`, so `cairn record` refuses this file, and should: a
# candidate becomes an evidence item when a person reads the corpus and
# labels it (docs/pilot-ca.md, "The question set"). Prompts are verbatim —
# spelling, case and all — because the phrasing is the data.
#
# Sources and their terms are in collect_queries.py's docstring. In short:
# `search-query` items are MS MARCO queries (Microsoft; non-commercial
# research), nationwide and from 2016–2018; `stackexchange` items are
# CC BY-SA 4.0 and carry the URL and asker the licence requires.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect candidate questions from public sources."
    )
    parser.add_argument("-o", "--output", required=True, help="candidates TOML to write")
    parser.add_argument("--msmarco", metavar="DIR", help="directory holding the MS MARCO TSVs")
    parser.add_argument(
        "--download", action="store_true", help="fetch the MS MARCO queries into DIR first"
    )
    parser.add_argument(
        "--per-topic", type=int, default=40, help="MS MARCO queries per topic (default 40)"
    )
    parser.add_argument("--seed", type=int, default=2026, help="draw seed (default 2026)")
    parser.add_argument(
        "--stackexchange", action="store_true", help="also query money/law.stackexchange"
    )
    parser.add_argument("--se-per-query", type=int, default=5)
    args = parser.parse_args(argv)

    items: list[dict] = []
    if args.msmarco:
        directory = Path(args.msmarco)
        if args.download:
            download_msmarco(directory)
        queries = read_msmarco(directory)
        drawn = select_msmarco(queries, per_topic=args.per_topic, seed=args.seed)
        print(f"MS MARCO: {len(queries)} queries scanned, {len(drawn)} drawn")
        items.extend(drawn)
    if args.stackexchange:
        drawn = fetch_stackexchange(sites=("money", "law"), per_query=args.se_per_query)
        print(f"Stack Exchange: {len(drawn)} questions")
        items.extend(drawn)
    if not items:
        print(
            "collect_queries: nothing to do — pass --msmarco DIR and/or --stackexchange",
            file=sys.stderr,
        )
        return 1
    Path(args.output).write_text(render(items, header=HEADER), encoding="utf-8")
    print(f"Wrote {len(items)} candidate(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
