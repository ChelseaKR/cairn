# The real-corpus pilot: federal, California, and a county

**Status: in progress. Nothing on this page is a measurement yet.** The
decision gate in the last section was written on 2026-08-23, before any
question was asked of any assembled corpus, and it is not to be edited after
the numbers exist. What *is* here already: the design, the tooling, the
first 131 pages scaffolded across five layers, one finding about county
terms that arrived before a single page was fetched and was resolved by
surveying all 58 counties, and observations from two smoke runs over
unreviewed scaffolds — labelled as such, and not to be quoted as results.

## What this pilot is for

`docs/pilot-usagov.md` measured Cairn against six real pages and found three
things the synthetic demo corpus could never have shown. Six pages is a
data point; it is not a deployment. This pilot builds the corpus a real
deployment would have — the federal program owner's page, the California
agency's page for the same program, and a county's page for the same
program, because a county human-services agency is the realistic Cairn
operator and its corpus is all three layers — and asks it the questions
real people ask, in their own words.

The question it answers is the one nobody has a number for: **at a
wrong-answer rate an agency would accept, what fraction of real questions
does the lexical-extractive core answer?** Everything after this pilot
hangs on that number — whether the next work is deployment hardening, a
content pipeline, or the generative-mode decision DESIGN.md has kept open.

Three things this pilot is not: a change to the engine (the measurement is
of the engine as it is, and the only code written for it is dev-only
tooling at the repository root); a change to the audited evidence
(`plumbline/bundle` and the gate are untouched; the pilot's question set is
recorded and graded as a separate target); and a deployment.

## The corpus: three layers, assembled per county

| Layer | Source | Size target | Why |
|---|---|---|---|
| `federal` | The program owners — SSA, Medicare, IRS, USCIS, VA, Federal Student Aid, FNS — not usa.gov's umbrella pages | ~130 pages | Public domain by statute; and the owners publish the numbers usa.gov defers |
| `california` | CDSS, DHCS, DMV, EDD, Covered California, FTB, the courts' self-help centre, the Secretary of State | ~170 pages | Where the dollar amounts, deadlines and fee schedules live; Spanish editions throughout; paired program by program with the federal layer |
| one county each: `san-mateo`, `sonoma`, `siskiyou` | County HSA/HSD/HHSA, housing, registrar, vital records, animal services | ~25 pages each | Office locations, hours, General Assistance (county-only), CAPI, IHSS — the layer where "contact your local office" bottoms out |

Programs are chosen in **pairs** so the same program exists at two or three
levels under different names: SNAP / CalFresh / the county's CalFresh
office; Medicaid / Medi-Cal; TANF / CalWORKs; LIHEAP / CA LIHEAP; EITC /
CalEITC; FAFSA / Cal Grant. That is the shape that produces the question
this corpus exists to measure: a person asks about "food stamps", the
federal page says "food stamps" in its title, the state page says
"CalFresh", and the county page has the address.

The three counties were first chosen for contrast — Los Angeles (the
largest DPSS in the country), Fresno (Central Valley, Spanish-dominant),
Siskiyou (rural; the thin-corpus case) — and then re-chosen by their terms
(Finding 0): **San Mateo** (~750,000 people, Bay Area, the largest county
whose terms permit this, and the one whose site answers the pilot's script
directly), **Sonoma** (~490,000, North Bay, a large Spanish-speaking
population — the Spanish-contrast county, since the Central Valley's either
forbid reuse or refuse automated reading), and **Siskiyou** (kept; its terms
turned out to permit this once they could be read). Solano is the reserve.
What the swap costs: no county at Los Angeles's scale, and no Central Valley
county. What it buys: a county layer that can be committed.

`[corpus] path` in `cairn.toml` names one directory, so a county corpus is
**assembled**: `assemble_corpus.py` copies `layers/federal/`,
`layers/california/` and `layers/<county>/` into one directory, writes a
`cairn.toml` whose `[refusal] contact` is that county's, and writes
`layers.json` recording which layer every document came from — the thing
flattening loses and the analysis needs back. A fourth assembly, `--combined`,
holds every county's layer at once. It is not a deployable corpus and is not
meant to be; it is the arm that measures what happens when a question with
fifty-eight correct answers is asked of a corpus holding three of them.

## Finding 0: two of three counties' terms forbid this, and the third cannot be read

This arrived on 2026-08-23, before any page was fetched, from reading the
terms pages the scope said to read first.

- **Los Angeles County.** `dpss.lacounty.gov` carries "© 2026 DPSS Site. All
  rights reserved" and links `lacounty.gov/user-rights/`, which says all
  contents "are owned by us, or by third parties who have licensed such
  Contents to us", that the County "expressly reserve[s] all rights", and
  that access "does not confer, and shall not be considered as conferring,
  upon you or any other user of the Website any license or other rights".
  No license is granted.
- **Fresno County.** `fresnocountyca.gov/Site-Features/Disclaimer`, under
  "Copyright/Trademark": "Any use of the materials stored on the County's
  website is prohibited without the written permission of the County of
  Fresno. [...] the following acts or activities are prohibited without
  prior, written permission [...]: (1) modification and/or re-use of text
  [...]; (2) distribution of the County's Website content; or (3)
  'mirroring' the County's information on a non-County server." That is an
  explicit prohibition on exactly what committing a corpus document is.
- **Siskiyou County.** The county's site moved to `siskiyoucounty.gov`,
  and the new host closes every non-browser connection (HTTP/2
  `ENHANCE_YOUR_CALM`, to this pilot's user agent and to a browser
  user-agent string alike). Its terms have not been read, and a layer whose
  terms nobody has read is not fetched from.

The state layer is different: `ca.gov/use/` says "information presented on
this website, unless otherwise indicated, is considered in the public
domain", and CDSS's own conditions-of-use page repeats it. The federal layer
is public domain by statute (17 U.S.C. §105).

So the county layer — the layer that makes this a deployment statement
rather than a retrieval experiment — cannot be committed to a public
repository from either of the two counties whose terms were readable. The
source lists for all three carry `blocked = "..."` with the quotation, and
`fetch_pages.py` refuses a blocked list. Three ways forward, none of them
this repository's to choose alone:

1. **Ask.** Fresno's terms name written permission as the path; a pilot
   with a partner county would have it. This is the right answer for a real
   pilot and the slow one.
2. **Fetch locally, never commit, report aggregates.** Fresno's own page
   quotes "private study, scholarship, or research" as the condition under
   which reproduction is permitted. The county layer would exist on one
   machine; the write-up would carry numbers and the question set, and no
   county text. Reproducibility suffers exactly as much as the terms
   require.
3. **Find a county whose terms permit it.** At first not found — San
   Francisco's disclaimer is silent on copyright, and silence is not
   permission — and then found, below.

**Resolved the same day, by the third way.** Every one of the 58 counties'
websites was surveyed on 2026-08-23 — homepage, then every footer link
whose address contained *terms*, *disclaimer*, *copyright*, *conditions*,
*legal*, *policy* or *user-rights*, then a search of those pages for the
phrases that decide the question. Twenty-three county homepages answered
403 or nothing at all to the pilot's user agent; a second pass with a
browser user-agent string, for reading terms only, got through to three of
them. Of the 58:

| Terms say | Counties |
|---|---|
| **Public domain in general** (the state's own sentence, near-verbatim) | San Mateo (`smcgov.org/endorsement-disclaimers`), Sonoma (`sonomacounty.gov/terms-of-use`), Solano (`solanocounty.gov/acceptable-use-policy`), Siskiyou (`siskiyoucounty.gov/…/website-terms-use`) |
| Re-use / distribution prohibited or requires written permission | Alameda, Calaveras, El Dorado, Fresno, Los Angeles, Marin, Nevada, Orange, Sacramento, San Joaquin, San Luis Obispo, Santa Cruz, Stanislaus |
| "All rights reserved" and nothing more | Alpine, Butte, Colusa, Lake, Lassen, Mariposa, Modoc, Mono, Napa, Placer, Plumas, San Diego, Sierra, Trinity |
| Terms page found, silent on reuse | Contra Costa, Humboldt, Inyo, San Bernardino, San Francisco |
| No terms page found on the homepage | Merced, Riverside, Santa Barbara, Tulare, Ventura, Yuba |
| Site unreadable to any non-browser client | Amador, Del Norte, Glenn, Imperial, Kern, Kings, Madera, Mendocino, Monterey, San Benito, Santa Clara, Shasta, Sutter, Tehama, Tuolumne, Yolo |

"Silent" and "all rights reserved" are not permission. Four counties say
yes in words, and all four say it with the same sentence `ca.gov/use/`
uses. The pilot's counties are now **San Mateo, Sonoma and Siskiyou**,
with Solano in reserve; Los Angeles and Fresno stay in `sources/` as
`blocked` records of what their terms say. The survey script is not
committed (it is a one-off and it read sites that asked not to be read by
scripts); the table is what it found, and each "public domain" row was
re-read by a person before being relied on.

The per-county assembly also warns and continues when a county layer is
empty, so a two-layer measurement is never blocked on a county.

One more thing Finding 0 says, which the scope predicted and is now
measured rather than predicted: the state-published county directory
(`cdss.ca.gov/county-offices`, in the California layer) carries every
county's office address and phone number under the state's public-domain
terms. The county layer's *location* questions may be answerable without
the county layer. Its General Relief, IHSS and hours questions are not.

## The question set

The first plan's primary source was eight to twelve people writing questions
to a form (`docs/pilot-ca-elicitation.md`). That needs eight to twelve
people, and on 2026-08-23 there were none to ask. What replaced it is
better in volume and arguably in realism, and worse in two specific ways
that are written down rather than waved at.

Three sources, tagged, kept separate in analysis:

- **Search queries (primary).** MS MARCO is about a million real,
  anonymised Bing queries released by Microsoft for non-commercial
  research. Filtered by the vocabulary of the pilot's programs — "food
  stamps", "medi-cal", "drivers license", "green card", in the words people
  type — about 12,000 match, and `collect_queries.py` draws a stratified,
  seeded sample: forty per topic plus every query that names California
  (79 of them). What this buys: phrasings nobody wrote for Cairn, from
  people typing into a box — "how long does it take to get food stamps",
  "what is the income guideline for wic", "ages to collect social security
  benefits". What it costs: the queries are **nationwide** (a query about
  Michigan's tax refund is a *refusal* case for a California corpus, and
  `names_other_state` flags those so the labeller sees it), **dated**
  (2016–2018; a query naming a year is naming that year), and **attributable
  to nobody's county** — so the `county` label means "the corpus this
  question is asked of", not "where the asker lives", and every question is
  asked of all three. `location_dependent` is still labelled from the
  question itself ("where do I apply" is; "what is the income limit" is
  not).
- **Stack Exchange (secondary).** Top-voted questions on
  money.stackexchange and law.stackexchange matching the same vocabulary,
  via the public API, CC BY-SA 4.0 with the URL and asker each item
  carries. Longer and more formal than a county caller, from people more
  financially literate than the median — the reason they are secondary.
- **Agency FAQ (control, ~50).** Questions as the agencies phrase them.
  Expected to answer at near 100%; if this set underperforms, the problem
  is not vocabulary.

`corpus/pilot-ca/candidates.toml` holds 564 candidates (372 search queries,
192 Stack Exchange), verbatim, with `source`, `topic`, `names_california`,
`names_other_state` and the attribution each source's terms require — and
**no** `behavior` or `answering_sources`, so `cairn record` refuses the
file, as it should. The collector's draw is seeded, so re-running it is a
diff. The elicitation form stays in `docs/` as the thing to run if people
become available; its questions would be tagged `elicited` and would be
the only ones with a real county attached.

A candidate becomes a question when a person labels it: `lang`,
`behavior`, `answering_sources` naming the passage a person says answers
it, `expected`, `load_bearing` and `fact_id` where a number is the answer
(`plumbline/questions.toml` is the template). A candidate that is
off-topic, or a real question the corpus cannot answer, is a `refuse` item,
not a discarded one — "who won medicare competitive bidding" is a real
thing someone typed. Four fields the recorder does not read and `sweep.py`
splits on: `source` (above), `jurisdiction` (`federal` | `california` |
`county` — the level the *correct* answer lives at), `county`, and
`location_dependent` (whether the correct answer changes by county: an
office address yes, a CalFresh income limit no).

Labelling happens **before** any corpus is asked anything. A question
relabelled after watching the engine refuse it is the experiment grading
itself. A second labeller covers a 20% overlap and the agreement is
reported.

## The runs

Every run is the documented pipeline and nothing else:

```text
$ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal
$ python3 import_corpus.py --batch source_pages/federal -o corpus/pilot-ca/layers/federal
  (review every file; delete `review: unreviewed`; add `reviewed_at`)
$ python3 assemble_corpus.py corpus/pilot-ca --county sonoma -o corpus/pilot-ca/assembled/sonoma
$ cairn --config corpus/pilot-ca/assembled/sonoma/cairn.toml index
$ cairn --config … lint
$ python3 probes_from_questions.py corpus/pilot-ca/questions.toml -o corpus/pilot-ca/probes.toml
$ cairn --config … calibrate --probes corpus/pilot-ca/probes.toml
$ cairn --config … record --questions corpus/pilot-ca/questions.toml --out pilot-ca-bundle
$ python3 sweep.py --config … --questions corpus/pilot-ca/questions.toml --at 0.165
```

Pages whose sites refuse scripts — ssa.gov and fcc.gov (403 to every
non-browser client), studentaid.gov and fns.usda.gov (HTTP/2 protocol
errors to headless Chromium), dhcs.ca.gov (an Incapsula challenge stub with
a 200), siskiyoucounty.gov (closes the connection) — are saved from a real
Chromium by `browser_save.mjs`, which reuses the Playwright
`tests/browser/` already pins. Three steps, one file each: `fetch_pages.py
--browser-jobs` writes the list of pages with no good copy; the browser
script saves them and leaves `browser-saved.json`; `fetch_pages.py
--hand-saved` registers them with `saved_by` and the URL the browser
actually landed on. Headless Chromium was enough for SSA, DHCS and
Siskiyou; Federal Student Aid, FNS, ACF and the FCC wanted a visible
window. The manifest says which.

The recorded bundle is graded by the pinned harness as a separate target,
with the harness's own default floors and no `floor_reason`s — this run is
measured, not gated.

**Treatment arms**, each against the same question set and the same labels,
the project's own bar for any change — build it, measure it, then decide:

1. Baseline: the template's defaults (`threshold = 0.165`,
   `max_passages = 1`).
2. `max_passages = 2` — `docs/pilot-usagov.md`, Finding 2; with paired
   documents this often composes federal + state together, and whether that
   reads as one answer or two half-answers is a labeller's call on a sample.
3. `dense_weight` at 0.10 / 0.15 / 0.25 — DESIGN.md's hybrid table was
   measured on 40 passages.
4. `split_intents = true`.
5. FAQ-pair authoring applied to the thirty worst wrong refusals — what the
   documented content fix buys per hour of authoring.
6. The income-limit and fee tables transcribed as prose, one row per
   sentence, against the same tables committed as `tables/*.csv` — what a
   lookup tool would buy against what authoring buys. (`cairn/tabular.py`
   implements one tool, counting rows; it does not do lookup, and this arm
   is where that shows.)

## The measurement

Per question, four cells: **correct answer** (composed from a passage the
question set names), **wrong answer** (composed, and none of it is one),
**correct refusal**, **wrong refusal**. `answer_rate` is correct answers
over answerable questions; `wrong_answer_rate` is wrong answers over all
answers given. `sweep.py` computes both at every threshold from one engine
call per question, because the deliverable is the curve, not a point on it
— the operating point is the agency's choice and the curve is what Cairn
can honestly hand them.

Reported overall, and split by `source`, `jurisdiction`, `county`,
`location_dependent` and language. Three splits are the pilot's own:

- **Jurisdiction routing** (per-county corpus): of questions labelled
  `california` or `county`, how many were answered from a higher layer —
  grounded, cited, correct as far as it goes, and without the number or
  the address.
- **Wrong-county rate** (combined corpus): of `location_dependent`
  questions, how many were answered from another county's page.
- **Thin-corpus refusal profile** (Siskiyou vs San Mateo on the same
  questions): what a small agency's first week looks like, and the first
  real exercise of `--refusal-stats`.

Every wrong refusal and wrong answer gets one label, first-pass from
`sweep.py --at` and then hand-reviewed: `vocabulary-gap`, `threshold`,
`wrong-passage`, `jurisdiction-mismatch`, `wrong-county`, `multi-intent`,
`cross-language`, `table-lookup`, `coverage-gap` (the corpus did not have
it — relabel, and count how many labels were wrong), `scaffold-defect`
(fix the extractor, re-run). The taxonomy, not the headline rate, decides
the next step.

## Observations from the smoke run of 2026-08-23 — not measurements

The first 28 federal pages were fetched, scaffolded, assembled with
`--allow-unreviewed` (nobody has reviewed them; the flag exists for exactly
this), indexed, and asked five questions by hand. This is a smoke test of
the pipeline. It is recorded because three of the five answers were wrong
in ways the extractor could fix mechanically, and one was wrong in a way it
cannot.

- **Page furniture won four of five questions** on the first pass. The
  extractor as it stood produced ~120 "paragraphs" per page — every menu
  entry, footer link, list item and table row — and "Begin", "Tools" and
  "Next step" outscored real content for the reason `docs/pilot-usagov.md`
  Finding 1 gives: short, and lexically present. Three rules fixed it:
  scope to `<main>`, emit headings as `##` so the chunker attaches them to
  the passage under them, and keep a list or a table as one block. Paragraph
  count fell to ~32 per page, and "What is the monthly income limit for the
  QMB program?" went from answering "If you qualify for the QMB program:"
  to answering with the 2026 limits table. Nineteen of the 28 pages had
  restated their title as the first body paragraph, which the importer now
  removes itself instead of asking the reviewer to.
- **"What vaccinations does my dog need?" was answered** — grounded, cited,
  at 0.167 against the 0.165 threshold — from a Medicare enrollment
  passage. The trace says why: the page's title is "When does Medicare
  coverage start?", titles are weighted into every passage of a document,
  and federal sites title pages as questions. "Does", "what", "how much",
  "when" become matching terms for the whole document, and a question
  contains exactly those words. The demo corpus never had a question-shaped
  title. This is the first thing the sweep should quantify, and it is a
  finding about the scorer rather than the corpus; it is written here so it
  is not discovered again in week three.
- **Interactive tool pages are not content.** "How much is the standard
  deduction?" answered from the IRS Interactive Tax Assistant page, whose
  first passage is "This interview will help you determine the amount of
  your standard deduction." The page is a questionnaire. Source selection
  is a review decision — it comes off the list — and the lesson for the
  URL lists is that a page's shape has to be checked, not only its status
  code.
- **Site bot rules shape the corpus.** ssa.gov and fcc.gov answer 403 to
  every non-browser client; studentaid.gov drops this pilot's user agent
  specifically; acf.hhs.gov returns a 202 challenge page. Sixteen of 44
  federal pages will be saved from a browser and registered with
  `fetch_pages.py --hand-saved`, which writes `status: "hand-saved"` so the
  manifest says which pages a script fetched and which a person did.

**Second smoke run, the same day, with the county layers in.** San Mateo
(16 pages) and Sonoma (17) fetched and scaffolded; Siskiyou's layer empty,
its pages still to be hand-saved. Four corpora assembled — one per county
and the combined one — and asked "Where do I apply for General
Assistance?", the county-only question, because General Assistance has no
federal or state page and the answer is a county address.

- **Every arm behaved as the scope predicted, first time.** Sonoma's corpus
  answered from Sonoma's General Assistance page; San Mateo's from San
  Mateo's. The **combined** corpus answered a question with two correct
  answers from whichever county's page happened to rank first — San
  Mateo's on one run, Sonoma's on the next after an extractor change moved
  the chrome around — which is `wrong-county` for half the people who
  could ask it. And **Siskiyou**, with an empty county layer, did not
  refuse: it answered from the Secretary of State's voting page (a
  heading "Do I need to show ID to vote in California?" shares *do*, *I*
  and *need* with the question). The thin-corpus arm's first data point
  is a wrong answer where a refusal was right.
- **Within the right document, page furniture kept winning the passage.**
  First the restated title (sonomacounty.gov has no `<main>`, so its
  breadcrumbs come first and its title third — the importer now drops a
  restated title wherever it sits), then "Who Is Eligible?" (a heading
  smcgov.org renders as `<p><strong>` — short question lines become `##`
  now), then "Human Services Department", then "Employment & Training
  Division". Each is a three- or four-word breadcrumb on a page without a
  `<main>` landmark. The furniture rule was widened once (three words, no
  digit, no sentence punctuation) and then left alone: the extractor is at
  the point where the next rule would be a judgement, and judgements are
  what review is.
- **And the dog.** "How do I license my dog?" against Sonoma's corpus
  answers from Sonoma County Animal Services' licensing page. The question
  that has been this repository's canonical refusal since its first
  README is a real county question with a real answer, which is the
  county layer doing exactly what it is for.

None of these is a number. The numbers come after review and labelling.

## The decision gate, pre-registered

Written 2026-08-23, before any measurement. Edit the numbers only in a
commit dated before the first sweep over labelled questions; after that,
they stand.

At **wrong-answer rate ≤ 5%** on the elicited and forum sets, per-county
corpus, arm 1:

- **Answer rate ≥ 70%** → the core holds. Next work is deployment
  (`docs/deployment.md`'s gaps, persistence, the index at scale).
- **40–70%** → content is the lever. Build the pipeline — recurring fetch,
  upstream-change detection, review queue, FAQ-pair authoring — and
  re-measure.
- **< 40%**, dominated by `vocabulary-gap` → the generative or query-side
  decision is forced, and this page is the evidence it is made on.

Two more numbers, reported beside the rate:

- **Jurisdiction precision ≥ 80%** on `california`- and `county`-labelled
  questions. Below that, the core cannot be deployed at a county without
  either scoping the corpus to one layer or a ranking change, and that is a
  decision for the write-up, not the sweep.
- **Wrong-county rate** in the combined corpus: no bar; above ~10% the
  pre-registered reading is that a multi-county corpus is not deployable
  without a location signal, and there is no third option.

## Effort, and where it stands

| Piece | Budget (h) | Done |
|---|---|---|
| URL lists, terms check, fetch, extractor, browser saves | 24 | Done for the draft lists: 58-county terms survey, counties re-chosen; 136 URLs listed, 132 fetched or browser-saved (43 federal, 35 California, 17 San Mateo, 17 Sonoma, 20 Siskiyou), 131 scaffolded. Four URLs 404 and come off the lists. Growing the lists toward the targets (~130 / ~170 / ~25 each) is the remaining work |
| Corpus review (~370 docs) | 40 | 0 |
| Questions (search queries, Stack Exchange, FAQ) | 16 | 564 candidates collected and committed; agency FAQ set not yet drawn |
| Labelling (+20% double-label) | 30 | 0 |
| Tooling (fetch, assemble, sweep, probes converter) | 9 | Done, tested |
| Runs (3 per-county + combined, 6 arms) | 18 | 0 |
| Write-up | 14 | This page |

Arabic: deferred on 2026-08-23. LA County DPSS publishes CalFresh and
CalWORKs material in Arabic, which would have been the first real Arabic
corpus content this project has had; Los Angeles is out on terms, and no
Arabic labeller is lined up. San Mateo and Sonoma publish in Spanish and
(San Mateo) Chinese and Tagalog, none of which is an interface language
beyond Spanish.

Forum-derived questions: decided 2026-08-23 — committed verbatim, titles
only, with attribution — and then superseded the same day by the search-
query and Stack Exchange sources above, which have clear terms and needed no
scraping of a site that forbids it.
