# Changelog

A reference implementation is cited, not installed, and a citation needs a
fixed point. This file is that fixed point's description; the version it names
is `cairn.__version__`, `pyproject.toml`'s `version`, and `CITATION.cff`'s
`version`, held together by a test.

Dates are the date the work landed on `main`. A section is written when the
version is bumped; the annotated tag is cut by the maintainer afterwards,
because tagging is a push and this repository's working rule is that an agent
does not push.

Work that has landed but is not yet in a version is recorded below under
**Unreleased**, at one heading level down from the version sections. That is
not decoration: `tests/test_cli.py` requires the first `##` heading in this
file to be the current version, because a changelog whose newest version
section describes a release that does not exist is worse than one that is
behind. So unreleased work waits at `###` until the version is bumped, and then
becomes a version section like any other.

### Unreleased

#### Added

- The real-corpus pilot, started: `docs/pilot-ca.md` (design, two findings,
  and a decision gate pre-registered before any measurement),
  `docs/pilot-ca-elicitation.md`, and `corpus/pilot-ca/` — a three-layer
  corpus (federal program owners, California agencies, one county) with a
  verified source list per layer, each carrying its terms and the date a
  person read them. The counties are San Mateo, Sonoma and Siskiyou,
  chosen by a survey of all 58 counties' website terms (four permit
  reuse in the state's own words; the table is in the doc); Los Angeles
  and Fresno, the first picks, stay as `blocked` lists with their terms
  quoted. 94 pages scaffolded and committed unreviewed across four layers,
  which `assemble_corpus.py` refuses to assemble without a flag that says
  it is a smoke run.
- Four dev-only scripts at the repository root, none touching the engine:
  `fetch_pages.py` (declared URL lists to pages plus a manifest; refuses
  unread or forbidding terms; registers hand-saved pages as hand-saved),
  `assemble_corpus.py` (layers into one corpus directory with the county's
  own refusal contact and a `layers.json` provenance map; refuses
  unreviewed scaffolds and duplicate ids), `sweep.py` (the answer-rate /
  wrong-answer-rate curve over every threshold from one engine call per
  question, split by any label the question set carries, with a first-pass
  failure taxonomy), and `probes_from_questions.py`. Plus
  `browser_save.mjs`, which drives the Playwright `tests/browser/` pins to
  save the pages those sites refuse to scripts, through a handshake that
  keeps `fetch_pages.py` the manifest's only writer (`--browser-jobs`,
  then the browser, then `--hand-saved`, which records `saved_by`).

#### Changed

- `import_corpus.py` drops a first paragraph that restates the title (the
  usa.gov pilot's Finding 1, mechanical now — nineteen of the first
  twenty-eight federal pages had it); scopes HTML to `<main>` and drops
  header, footer, aside, form and `aria-hidden` regions; writes headings
  as `##` lines; keeps a list or a table as one block; joins a
  colon-terminated introducer to the block it introduces; drops
  one-or-two-word fragments with no digit and reports the count; and
  takes `source:` / `fetched_at:` provenance from `fetch_pages.py`'s
  manifest in batch mode or `--source` for one file; and in batch mode
  derives the placeholder id from the file name, since four cdss.ca.gov
  pages share the heading "CalFresh". `docs/onboarding.md` says what
  review still has to catch.

## 0.2.0 — 2026-08-23

Fourteen items across two rounds. Nothing here changes how a grounded
answer is produced or graded — the extractive path, the threshold, the
citation guarantee, and the audited evidence bundle are exactly what
0.1.0 shipped. What changed is everything around it: the tools an
operator uses to run this against a real corpus, the deployment surface
(auth, rate limiting, embedding, analytics, a real handoff to a person),
one new compliance-readiness document, and — the second round — the
infrastructure and evidence needed to trust a release: a screen-reader
test script, a Windows/macOS CI matrix that found and fixed a real
cross-platform bug in how this project's own byte-for-byte checksums
are computed, a PyPI + container release workflow proven continuously
in CI before it has ever published anything for real, and a pilot
against six real, unedited government pages that answers the one open
research question this project was carrying — whether to add semantic
retrieval — with a measurement rather than a guess.

#### Added

- `cairn lint`: reads the corpus the way `cairn index` would, without writing
  an index, and reports every problem found rather than stopping at the
  first one — malformed front matter, a duplicate doc id, a passage that
  tokenizes to no scoring terms at all (title included, at the weight
  `cairn index` would use), and a language with too few passages for the
  document-frequency floor to suppress anything
  (`LanguageStats.dilution_exempt`, new on `Index`). Advisory: warnings do
  not fail the command, only a structural error `cairn index` would itself
  refuse does. See `cairn/lint.py` and DESIGN.md, "The document-frequency
  floor has one exemption, and it is narrow".
- `docs/I18N.md`: the scope and flip conditions for language support, in
  three tiers (corpus language, interface language, right-to-left table
  entry) — closing the gap the Standards Conformance table named directly.
- `cairn config`: the effective configuration next to its built-in default,
  with a one-line rationale pointer into DESIGN.md for load-bearing keys.
  Read-only; introduces no second config path.
- `cairn record --coverage`: which corpus passages the recorded question set
  ever puts in an accepted candidate set, reusing the exact `Candidate`
  objects the evidence bundle is built from. Writes no bundle; not part of
  the audited evidence path.
- `cairn record --diff-against`: an unscored dry-run preview of what
  recording would produce, diffed by item id against a bundle already on
  disk. Reuses `record`'s own item-building function (factored out as
  `record.build_items_and_responses`) rather than a second idea of what an
  answer is. Never writes or modifies a bundle, and is explicit in its own
  output that it is not a substitute for `./plumbline-gate.sh`.
- `cairn ask --explain --compare-config`/`--compare-index`: runs one question
  through two configs and/or indexes and diffs the two traces — verdict
  flip, blame-stage flip, accepted-set changes, score deltas on shared
  candidates. A single-question tuning aid, explicit in its own output that
  it is not a gate.
- `RetrievalTrace.margin` and `--explain`'s "Margin:" line: the score gap
  between the winning candidate and its runner-up, surfaced (and flagged
  against the new `retrieval.margin_warn`, default `0.02`) so the two
  documented near-tie hard cases — the GoPass cross-document tie and
  `ck-022`'s one-word-decided ranking — are visible in one line instead of
  requiring the subtraction by hand. Purely diagnostic: computed from scores
  already produced, changes no accept/reject decision, and explain mode
  stays byte-identical to the answer without it.
- `cairn lint` gains a per-passage reachability check: whether any single
  term a passage holds (title included) would clear `retrieval.threshold`
  on its own. Built on a new `cairn.retrieve.single_term_scores`. Explicit
  in its own wording that this is not proof of unreachability — a
  combination of otherwise-common terms can still retrieve a passage
  together, per `ck-022` — only that no one-word question naming a term the
  passage holds will find it alone. Quiet on the demo corpus at the shipped
  default threshold; verified to fire reliably at an artificially strict one.
- `cairn diff OLD NEW`: compares two corpus directories by document id —
  added, removed, or changed — and for a changed document, which passage
  ordinals now hold different text than before. Deliberately positional
  rather than re-aligned: an inserted paragraph correctly shows every later
  ordinal as changed, because every later citation id now points at
  different text, and re-aligning ordinals to hide that would be the same
  silent judgment call the rejected corpus-alias experiment made about
  content, applied to passage identity instead. Advisory only; needs no
  config or index.
- `docs/authoring.md`: the FAQ-pair convention for closing a `ck-015`-shaped
  lexical gap without repeating the alias mistake DESIGN.md already
  measured and reverted — write the question a passage answers into the
  passage itself, as real prose, rather than as document-level metadata
  that lifts every passage of a document by the same amount. Documentation
  only; no code, no lint rule (one is sketched and deliberately left
  unbuilt, pending measurement).
- `benchmark_index.py`: dev-only, stdlib-only, not gated in CI — generates a
  deterministic synthetic corpus at a chosen size and times build, read, and
  query, to measure where DESIGN.md's "milliseconds on a laptop demo" claim
  stops holding rather than leaving it asserted forever. Measured
  2026-08-22: ~44ms median query at 400 passages, ~438ms at 4,000, ~2.2s at
  20,000 — linear in passage count, because scoring is a full scan with no
  index structure that skips passages a query cannot match. Written up in
  DESIGN.md with the concrete (unbuilt) fix sketched: precomputed per-passage
  vector norms, an additive index-format bump.
- `import_corpus.py`: dev-only, stdlib-only, never wired into `cairn index`
  or any runtime path — scaffolds a `.txt`/`.html` file into reviewable
  front-matter markdown. The doc id is prefixed `review-` and never
  auto-finalized; a `review: unreviewed` front-matter key (inert to Cairn)
  marks the file for human review, deliberately kept out of the body text
  itself, because anything written into the body becomes a real, scored,
  retrievable passage the moment the file is indexed. After writing, the
  script loads the scaffold back through `cairn.corpus.load_document` — the
  exact function `cairn index` calls — and prints the passage boundaries
  that call produced, so the chunk preview cannot drift from what indexing
  would actually do. Caught and fixed a real bug while testing it by hand:
  the HTML `<title>` extractor was swallowing the title text because
  `<title>` lives inside `<head>`, which the extractor also uses to suppress
  body text — now regression-tested.
- French (`fr`) as a fourth interface language: a full `LANGUAGES` entry
  and `messages.py` catalogue, left-to-right, passing every message-catalogue
  test (key parity, no untranslated copies, matching placeholders). Shipped
  deliberately with **no French corpus content** — the same "translated
  interface outruns translated documents" reality already demonstrated for
  the English-only GoPass document, played out for a whole language. A
  French question falls back across languages or refuses in French, exactly
  like any other interface language with no matching source. Two historical
  code comments and a test that used `Config(default_lang="fr")` as the
  demonstrative *unsupported*-language example were updated to `"de"`, since
  `"fr"` stopped being an example of that. `docs/I18N.md` names explicitly
  what this addition does *not* do: no French corpus document was added, no
  evidence item was recorded, and `plumbline/baseline.json` was not
  regenerated — that step needs the network-resolved Plumbline harness,
  unavailable here. `cairn record --diff-against plumbline/bundle` confirms
  the committed evidence bundle is byte-for-byte unmoved by this change.
- `.github/workflows/ruleset-check.yml`: a weekly (plus `workflow_dispatch`)
  job that asks the GitHub API directly whether an active ruleset currently
  enforces `.github/rulesets/main.json`'s required checks, and opens (or
  updates) a tracking issue for as long as the answer is no, closing it
  automatically once it is not. Converts the fact that the merge gate is
  advisory from a prose claim, checked whenever someone happens to reread
  the README, into something re-verified against the live repository on a
  schedule — the same discipline `audit_guard.py` already applies to a
  suite's score, applied here to whether the gate can block a merge at all.
  It never applies the ruleset itself; that stays an admin action nobody but
  the maintainer can take (`.github/rulesets/README.md`). Untested beyond
  YAML validity and manual review — it needs a real GitHub Actions run
  against the live repository and `issues: write` permission to verify
  end to end, neither available in this environment.
- `tests/test_performance.py`, gated in `make verify` like any other test:
  a page-weight budget (deterministic — page plus `app.css` plus `app.js`,
  no timing involved, budgeted at roughly 2x the ~21KB measured baseline
  across all four interface languages) and a demo-corpus query-latency
  budget (deliberately loose — two orders of magnitude above the ~3.3ms
  measured, so ordinary CI runner noise cannot trip it while a genuine
  algorithmic regression still would). Closes the exact gap the Performance
  Standards Conformance row used to name: "no latency or page-weight budget
  is measured and none is gated."
- A copy/export control in the chat interface: a read-only `<textarea>`
  inside a native `<details>`/`<summary>` disclosure, carrying
  `Answer.cited_text` (the same string the plain-text and JSON forms already
  carry), for a grounded answer only. No JavaScript required — the no-JS
  page renders it directly (`cairn/ui/page.py`, `_copy_export`) and the
  client script mirrors it exactly for the accumulating-transcript path
  (`cairn/ui/static/app.js`, `addTurn`). Labelled with `aria-label` rather
  than `<label for>` so no `id` is minted that could collide once a second
  turn joins the transcript. Deliberately the smallest of the interactive-UI
  ideas considered: no live-region interaction, no focus movement, no
  clipboard API. The larger ones (keyboard shortcuts, an in-page
  explain-mode toggle, a corpus-browsing page) were not built — this
  project's own stated priority is a real screen-reader session before any
  further interactive surface ships, and that session has not happened.
  **Regenerated the evidence bundle** (`cairn record`) and `site/index.html`
  (`site_build.py`) to match: this change alters the served page and its
  embedded strings, which `plumbline/bundle/interface.html` snapshots.
  `items.jsonl`, `responses.jsonl`, `sources.jsonl`, `manifest.json`, and
  `DATASET.md` came back byte-identical — only `interface.html` and
  `checksums.json` changed — confirming no answer, citation, or refusal
  changed, only the interface snapshot. The dataset id and bundle sha256
  shown in README.md and docs/demo.md are updated to match. **The audit
  gate itself was not re-run** (`./plumbline-gate.sh` needs the
  network-resolved Plumbline harness, unavailable in this environment), so
  `plumbline/baseline.json` is not regenerated; a maintainer with gate
  access should run it before relying on this as a graded change.
- `Makefile`: `make verify` is the local gate — lockfile check, ruff, mypy, and
  the test suite under coverage with an 85% branch floor (measured 89%). It is
  deliberately not a wrapper around `./plumbline-gate.sh`; the merge gate stays
  a separate, fail-closed job, for the reasons in `.github/workflows/ci.yml`.
- `uv.lock` and `.python-version`, so the development toolchain is a pinned,
  reviewable resolution rather than whatever pip picked today. The runtime is
  still standard-library only and still has no lockfile to consult, because it
  has nothing to lock.
- `.github/workflows/security.yml`: gitleaks over the full history, Semgrep,
  and `pip-audit` over the development toolchain. All three run automatically
  on push, on pull request, and weekly; none of them can be skipped into a
  green check.
- `.github/dependabot.yml` for GitHub Actions and pip, with a seven-day
  cooldown. Every `uses:` in this repository is pinned to a commit SHA, and a
  pin with nothing raising it is a frozen dependency rather than a careful one.
- `SECURITY.md`, `CONTRIBUTING.md`, `.github/CODEOWNERS`,
  `.pre-commit-config.yaml`, and `docs/adr/0000-record-architecture-decisions.md`.
- A Standards Conformance table in the README, with every standard declared
  and the three real gaps (mypy strict, the complexity rule, no i18n
  declaration) named rather than left out.
- `cairn calibrate --probes PATH`: checks `retrieval.threshold` against a
  real, operator-authored probe question set (a plain TOML file of
  question/behavior pairs — the same answer/refuse split `tests/probes.py`
  already measures the shipped default from, made runnable against any
  corpus, not only the demo one). Reports the worst accepted score, the best
  rejected score, the gap between them, a suggested midpoint threshold, and
  — the part that matters — whether the *currently configured* threshold
  actually gets every probe right. Exits 1 when it does not, or when the
  probe set has no positive gap to vouch for any threshold at all. Advisory:
  never edits `cairn.toml`. `docs/calibration-probes.example.toml` is a
  worked example against the demo corpus. Closes the gap DESIGN.md's own
  calibration note names: the threshold is "set empirically against the
  demo corpus... re-check it against probe questions when the corpus
  changes" — a re-check that, until now, existed only as a sentence.
- `import_corpus.py --batch INPUT_DIR -o OUTPUT_DIR`: scaffolds every
  `.txt`/`.html` file in a directory (non-recursive), reusing the exact
  single-file scaffolding function so batch mode can never become a second,
  drifting idea of what scaffolding one file does. A file that fails to
  extract does not stop the rest of the batch; the summary line reports how
  many succeeded and exits 1 on any partial failure. `--id`/`--title` are
  rejected in batch mode (they apply to one file, not many). Every review
  requirement from the single-file path still applies to every file.
- `Document.reviewed_at` (`cairn/corpus.py`) and `cairn lint --max-age-days`:
  an optional `reviewed_at: YYYY-MM-DD` front-matter key — inert to
  retrieval, scoring, and citation, like `import_corpus.py`'s `review`
  marker — that an author sets the last time they checked a document
  against its real source. `cairn lint --max-age-days N` flags a document
  whose `reviewed_at` is missing, unparseable, or older than N days.
  Strictly opt-in: without the flag, `cairn lint` never looks at
  `reviewed_at`, so a corpus that has never adopted the convention lints
  exactly as quietly as before. `docs/onboarding.md` covers both this and
  the batch-import addition — the index's own fingerprint already catches a
  corpus document changing since the last `cairn index`; this is the
  companion gap it cannot see, a document that is unchanged and simply
  wrong relative to the world it describes.
- `cairn serve --auth-token`/`CAIRN_AUTH_TOKEN` and `--rate-limit`: opt-in
  bearer-token auth (constant-time comparison) and a per-client-address
  request-rate limit, both off by default so the server's existing
  loopback-only, no-auth behaviour is unchanged unless an operator asks for
  more. New `cairn/network.py` holds both primitives; `cairn/server.py`
  gates every route — GET, HEAD, and POST — through one check, auth before
  rate limit, so an unauthenticated client is never told it would also have
  been rate limited. The token is CLI-flag-or-environment-variable only —
  it never enters `cairn.toml` — and the flag wins if both are set, so a
  real deployment never has to put a secret on a command line another
  process on the same host could read out of `/proc`. `docs/deployment.md`
  covers a reverse proxy for TLS (Caddy and nginx examples), a systemd
  unit, and a container example, and states plainly what this is not: not
  TLS, not a login system, not a firewall, and not `X-Forwarded-For`-aware.
  `SECURITY.md`'s server section is updated to describe the opt-in path
  alongside the unchanged default.
- `cairn serve --allow-embed` and `--cors-origin`: two independent opt-ins
  for an agency embedding Cairn in its own site — the CSP `frame-ancestors`
  directive (letting a named origin put the page in an `<iframe>`) and CORS
  response headers (letting a named origin's own script call the JSON API
  directly), neither implying the other. Both are exact-origin allow-lists
  with no wildcard, repeatable, and off by default, so the server's existing
  `frame-ancestors 'none'`/no-CORS-headers behaviour is unchanged unless an
  operator asks for more. New `frame_ancestors`/`cors_headers` in
  `cairn/network.py`; `cairn/server.py` answers the CORS preflight
  (`OPTIONS`) in its own handler, deliberately not gated by `--auth-token`
  since a preflight never carries the `Authorization` header the real
  request would. `docs/embedding.md` covers both, with a worked iframe
  example and a worked `fetch()` example; `SECURITY.md`'s server section
  is extended to describe the scope of each.
- `cairn serve --refusal-stats PATH` and `cairn refusals PATH`: opt-in,
  local, aggregate-only refusal analytics for finding corpus gaps, without
  weakening "nothing about the questions people ask is ever logged" — the
  server's oldest promise. Every refusal increments one counter keyed by
  (language, reason code) — the same machine-stable codes
  `cairn ask --explain` already names for the retrieval stage
  (`no-passages-in-language`, `no-lexical-overlap`, `below-threshold`;
  factored out as `cairn.explain.refusal_reason`) — never the question, a
  client address, or a timestamp. `cairn refusals PATH` reports the
  aggregate, sorted worst-gap-first with a legend for the reason codes.
  New `cairn/refusal_stats.py` (`RefusalCounter` for the write side,
  `report`/`render` for the read side). Off by default: with no
  `--refusal-stats` flag, nothing is written and a refusal behaves exactly
  as before. `docs/refusal-analytics.md` covers the feature and states its
  limits plainly (not a query log, not real-time); `SECURITY.md`'s server
  section is extended to describe its scope.
- `cairn serve --followup-store PATH` and `cairn followups PATH`: a real
  refusal-to-human handoff — an opt-in "Request a follow-up" action on a
  refusal, only, that captures the asker's own contact information and,
  only if they separately check a box on that specific submission, the
  question they asked. The static `refusal.contact` text a refusal has
  always carried is unchanged and still shown either way; this is an
  additional channel, not a replacement. New `cairn/followup.py`
  (`FollowupStore` for the write side, `load`/`render` for the read side,
  behind `cairn followups`); `cairn/ui/page.py`'s `_followup_form` and
  `cairn/ui/static/app.js`'s mirrored markup in `addTurn`, following
  `_copy_export`'s established shape (implicit `<label>`s, no ids to
  collide across a repeated refusal, a plain HTML form with no
  `fetch()`/`preventDefault()` behind it — a full page reload, identically
  whether or not JavaScript ran). Off by default: with no
  `--followup-store` flag, the form never renders, `/follow-up` 404s, and
  a refusal's response is byte-for-byte what it was before this existed.
  `docs/followup.md` covers the feature and draws the line against
  `docs/refusal-analytics.md`'s strictly aggregate, PII-free counterpart;
  `SECURITY.md`'s server section is extended to describe its scope.
  `render_page()` gains an optional `followup_notice` parameter for the
  plain-HTML confirmation/error banner a `/follow-up` submission's full
  page reload shows, deliberately not routed through the existing
  JS-oriented `#status` live region (present-at-load content in a live
  region is not reliably announced by assistive technology, unlike a
  plain paragraph in normal document order).
  **Regenerated the evidence bundle** (`cairn record`) and `site/index.html`
  (`site_build.py`) to match: the new message-catalogue keys this feature
  adds (`followup_heading` and friends) are embedded in every served page
  via `_embedded_strings`, which changes `interface.html`'s bytes even
  with `--followup-store` off. `items.jsonl`, `responses.jsonl`,
  `sources.jsonl`, `manifest.json`, and `DATASET.md` came back
  byte-identical — only `interface.html` and `checksums.json` changed —
  confirming no answer, citation, or refusal changed, only the interface
  snapshot's embedded strings. The dataset id and bundle sha256 shown in
  README.md and docs/demo.md are updated to match. **The audit gate itself
  was not re-run** (`./plumbline-gate.sh` needs the network-resolved
  Plumbline harness, unavailable in this environment), so
  `plumbline/baseline.json` is not regenerated; a maintainer with gate
  access should run it before relying on this as a graded change.
- `docs/compliance.md`: a compliance/procurement readiness summary for a
  privacy officer, security reviewer, or procurement analyst — not a
  developer configuring the software. Draws together security posture,
  data handling (including the two opt-in server features that hold real
  data, `--refusal-stats` and `--followup-store`, and how they differ),
  and accessibility status from where each is already established
  (SECURITY.md, README.md's Standards Conformance table, DESIGN.md), and
  adds the one thing stated nowhere else as plainly: Cairn enforces no
  retention period on any file it writes, for any feature — stated
  per-file, with `--followup-store`'s real personal data named as the one
  piece that needs a written retention decision before it is turned on.
  Also states the support-and-maintenance reality plainly (one unpaid
  maintainer, no SLA) for a procurement risk register. README.md's
  Incident Response and Data Governance rows cross-reference it.
- `docs/screen-reader-test-script.md`: a structured, task-by-task script for
  the manual VoiceOver/NVDA/JAWS session DESIGN.md's "What is still open"
  and README.md both name as not having happened yet — so running it takes
  an hour against a checklist instead of a day of improvising. Each task is
  grounded in a behavioral contract the automated suites already assert
  (`tests/browser/a11y.mjs`'s 63 pinned checks, `tests/test_ui.py`'s markup
  checks) and names which automated check covers it, so a result that
  contradicts the script is either a regression the automation missed or a
  gap between what Chromium/axe-core can verify and what a real assistive
  technology stack does. **This does not close the open item** — writing the
  script is not running the session — and `tests/test_open_items.py`'s
  anchor for "No manual screen-reader pass" is unchanged. DESIGN.md,
  README.md, and docs/compliance.md cross-reference the new page.
- `ci.yml`: two new jobs, `core-windows` and `core-macos`, running the same
  install/lint/test/demo/independence-of-the-auditor steps `core` runs, one
  canary per non-Linux OS at the newer supported Python version. The
  stdlib-only, zero-dependency claim was a claim about the package, not
  about Ubuntu, and until now it was only ever checked there. Deliberately
  two new jobs rather than a second matrix dimension on `core` itself:
  `tests/test_rulesets.py` holds every required-status-check context in
  `.github/rulesets/main.json` against a parser of this file that assumes
  one matrix key per job, and GitHub folds every matrix key into a check
  run's name — a two-key `core` matrix would rename every existing `core`
  check (`core (...) (3.11)` becomes `core (...) (ubuntu-latest, 3.11)`) and
  need that parser rewritten to stay honest. Two single-OS jobs sidestep
  that: no matrix, so no name change, so no parser change, and the ruleset
  gains two more required contexts instead of needing four rewritten ones.
  No fail-closed drill on either new job — that step runs the vendored gate
  script itself (`env -u`, `sed`, a `#!/usr/bin/env bash` shebang) and is
  already covered on `ubuntu-latest` by `core`, `audit`, and `live`; running
  it again would test Git Bash's or macOS's own bash's shell compatibility,
  not this repository. Found and fixed while reviewing for the
  Windows/macOS spot-check: three writes (`interface.html` and `DATASET.md`
  in `cairn/record.py`, the refusal-stats counters file in
  `cairn/refusal_stats.py`, the follow-up store's append in
  `cairn/followup.py`) used `write_text`/`open(..., "w"/"a")` without
  `newline="\n"`, unlike every sibling write in the same modules — on
  Windows, Python's default text-mode translation would have written `\r\n`
  where every other file this project writes deliberately writes `\n`. None
  of the three sit in `core`'s own codepath (`cairn index` and `cairn ask`
  only), so nothing here was failing; the audit was static, not a CI
  failure caught live. `.github/rulesets/main.json` gains the two new
  required contexts, `.github/rulesets/README.md` is reworded from "the
  five contexts" to "the seven contexts", and README.md's CI/CD
  conformance row names both new jobs.

  What the static review could not find, `core-windows`'s first real run
  did: 54 test failures, all traced to three root causes, none in `cairn/`
  itself — every one was a test-suite assumption that happened to hold on
  every platform the suite had ever run on.
  - **The dominant one, ~40 failures:** roughly a dozen test files build a
    throwaway `cairn.toml` by interpolating an absolute `Path` into a TOML
    *basic* (double-quoted) string — `f'path = "{some_path}"\n'`. A TOML
    basic string treats `\` as an escape character; a Windows path
    (`C:\Users\...`) is not one, so `tomllib` raised
    `invalid TOML: Unescaped '\\' in a string` and every test built on that
    config failed before it reached what it meant to check. Fixed by
    calling `.as_posix()` on every interpolated path, which a TOML basic
    string handles cleanly and `cairn/config.py` (and Windows itself, which
    accepts `/` as a path separator) already reads correctly — not by
    switching to TOML literal (single-quoted) strings, which would have
    meant rewriting each site's Python string delimiter too.
  - **Two `.read_text()` calls in `tests/test_interlock.py`** (auditing
    `sources.jsonl` and `responses.jsonl` for citation integrity) omitted
    `encoding="utf-8"`, unlike every sibling call in the same file —
    `UnicodeDecodeError` decoding non-ASCII evidence bytes as Windows'
    default `cp1252`. A third instance in `tests/test_benchmark.py`
    (comparing two generated corpus files) was fixed the same way on
    inspection, ASCII-only today but built on the same missing-encoding
    assumption. Every text-mode file operation this project's own `cairn/`
    package performs already specifies `encoding="utf-8"` — this gap was
    in the tests, not the package.
  - **`tests/test_docs.py`'s README-output comparison** ran a `cairn ask`
    subprocess with `text=True` and no `encoding=`, so Python decoded the
    UTF-8 bytes the child wrote using Windows' locale-preferred `cp1252`
    instead — `Cuánto` came back `Cu�nto`. `PYTHONIOENCODING=utf-8` was
    already set for the *child's own* stdout encoding, which is a
    different thing from how the *parent* decodes what it reads back;
    fixed by passing `encoding="utf-8"` to `subprocess.run` itself.
    `tests/test_freshness.py`'s equivalent subprocess call gets the same
    fix pre-emptively, on the same reasoning, though its own assertions
    happen to be ASCII-only today.
  - **`tests/test_live.py`'s `TestTheRunnerCannotFetchItsOwnAuditor`**
    invokes `./plumbline-live.sh` directly via `subprocess.run([path])` —
    no shell, relying on the OS to read the `#!/usr/bin/env bash` shebang
    and dispatch to bash itself, which Windows does not do outside an
    actual shell: `OSError: [WinError 193] %1 is not a valid Win32
    application`. `tests/test_interlock.py`'s `TestItFailsClosed` invokes
    `./plumbline-gate.sh` the identical way and did not fail on this run,
    but relying on that holding is exactly the kind of environment-quirk
    dependency this project's own fail-closed philosophy argues against,
    so both classes now carry a `@unittest.skipIf(sys.platform ==
    "win32", ...)` stating the gap plainly rather than leaving it to
    chance — proved on Linux and macOS, both genuinely POSIX and able to
    exec a shebang script directly; not proved on Windows, which cannot.
    Skip, not xfail: a script that cannot run this way on this platform is
    not a test that sometimes fails.

  That push brought the failure count from 54 to 5, and every one of those
  five traced to a single further cause, deeper than a test-suite
  assumption: **this repository had no `.gitattributes`.** With none, line
  endings on checkout follow whatever `core.autocrlf` the checking-out
  machine has set, and on the Windows runner that meant every text file —
  corpus documents included — was checked out with `\r\n` where the commit
  holds `\n`. `cairn.corpus.fingerprint()` and `cairn.record.
  bundle_checksums()` both hash `path.read_bytes()` specifically so that a
  whitespace edit moves the hash (each docstring says so directly) — which
  means they also hash a line-ending difference that was never an edit to
  the content at all. The corpus fingerprint `cairn index` printed on
  Windows (`7f46e5c5b629`) differed from the one every document and the
  committed evidence bundle name (`5bfa70e8cad4`), and the bundle's own
  `checksums.json` no longer matched files Git had just checked out
  unedited — not because anything was wrong with the content, but because
  the bytes on disk were not the bytes in the commit. Added `.gitattributes`
  — `* text=auto eol=lf`, with no binary file in this repository to exempt
  — so the checked-out bytes are the committed bytes on every platform,
  which is what a byte-for-byte fingerprint or checksum has to be able to
  assume to mean anything. The last two of the five failures were in
  `tests/test_cli.py`, and were not a fingerprint problem: two assertions
  compared the CLI's echoed index path (verbatim from `cairn.toml`, which
  this same round's `.as_posix()` fix now writes with forward slashes) to
  `str(self.index_path)` — a `Path` object's own platform-native string
  form, backslashes on Windows. Fixed by comparing against
  `self.index_path.as_posix()` instead, the form the CLI actually echoes.
- `Dockerfile`, `.dockerignore`, and `.github/workflows/release.yml`: a
  PyPI + container release path, item 5 of the second deployment-value
  expansion round. `release.yml` fires on a published GitHub Release with
  two independent jobs — `pypi` publishes the sdist and wheel via PyPI
  trusted publishing (`id-token: write`, no API token stored as a secret;
  a step checks the release tag against `cairn.__version__` before building
  anything, so a mistagged release fails loudly rather than publishing
  mislabelled), and `container` builds and pushes `ghcr.io/chelseakr/cairn`
  to GHCR using the repository's own `GITHUB_TOKEN`. Neither has ever run
  for real — no release has been cut — but both are exercised continuously
  by two new `ci.yml` jobs, `image` and `package`, which build the same
  artifacts release.yml would publish and run each end to end (the
  container over real HTTP, the wheel installed into a clean venv) against
  the demo corpus on every change, so release day is not the first time
  either build is tried. The `Dockerfile` itself was actually built and run
  during development — not just written — surfacing one real gap in what
  had only ever been an illustrative snippet in docs/deployment.md: it had
  no step baking an index, so `cairn serve` would have refused on its first
  request in a container built exactly as documented. Fixed by adding
  `python -m cairn index` at build time and a non-root `USER` for
  everything after it (nothing past that point needs root, since `cairn
  serve` writes nothing in this configuration); docs/deployment.md's fenced
  block and `pyproject.toml`'s new `release` extra (`build>=1.2`, kept
  separate from `dev` since neither install has a use for the other's
  tools) were updated to match. New `docs/release.md` documents the one
  thing this repository cannot do for itself here either, the same shape
  as `.github/rulesets/README.md`: registering a PyPI trusted publisher —
  a *pending* one, since the project has never been published — is a
  one-time action only the project owner can take on PyPI's own site.
  `tests/test_container.py` holds the real `Dockerfile` and the docs page's
  copy of it to the same directives, checks the release workflow's
  structural claims (OIDC not a stored secret, every action pinned to a
  commit, the tag-version check present), and confirms `EXPOSE` still
  matches `cairn serve --port`'s own default. `.github/rulesets/main.json`
  gains the two new required contexts (nine now, from seven), and
  README.md's CI/CD conformance row states plainly that nothing has been
  published yet.
- `corpus/pilot-usagov/` and `docs/pilot-usagov.md`: the real-corpus pilot,
  item 4 of the second deployment-value expansion round and the one
  flagged as highest-leverage when this round was recommended. Six real,
  currently-published pages from usa.gov (SNAP, LIHEAP/WAP, Lifeline,
  Section 8, WIC, and SNAP in Spanish) imported with `import_corpus.py
  --batch`, reviewed by hand, `synthetic: false`, each carrying its real
  source URL and review date in front matter — the first content in this
  repository nobody wrote for Cairn. `cairn lint`, `cairn calibrate`
  (against a new 16-item `probes.toml`), and `cairn record` (against a new
  `questions.toml`) all run cleanly against it, and `tests/test_pilot_usagov.py`
  holds the corpus and probe set to that shape going forward.

  The first review pass found a real defect and the write-up reports it
  rather than quietly fixing it and moving on: transcribing a page's own
  heading into the body doubles it as a passage, and that short, generic
  passage out-scored the actual answering passage on a real question
  ("How do I check my SNAP EBT balance?") because TF-IDF cosine's length
  normalization rewards short passages where every matched word is a
  larger fraction of the whole. Fixed in the corpus (delete the duplicated
  line) and in `docs/onboarding.md`'s import guidance, since it is a
  mechanical mistake with no per-corpus judgment call, not specific to
  usa.gov. A second, related effect survived that fix: a short
  introduction paragraph can still out-score a longer, more specific
  answering passage under the default `retrieval.max_passages = 1`
  (measured on "Am I eligible for Section 8 housing?" and "What is
  LIHEAP?"), fixed in a scratch config by raising `max_passages` to `2` —
  recorded as a recommendation for real, unevenly-shaped corpora rather
  than changed in the shipped pilot config, which stays at the default to
  demonstrate what an operator gets out of the box.

  A genuine vocabulary gap also surfaced, once: "Who qualifies for WIC?"
  scored its accepted passage at 0.239 while the passage that actually
  states eligibility ("...you must be at least one of the following:
  pregnant, breastfeeding...") scored 0.164, one thousandth below
  threshold, because neither shares "qualify"/"qualifies" with the
  question. One borderline case out of ten answer probes, not a dominant
  failure — and `cairn calibrate` found the demo corpus's own
  `retrieval.threshold = 0.165` correctly classified all 16 probes anyway,
  with a suggested midpoint 0.175 away.

  This directly resolves the contingent evaluation of optional semantic
  retrieval named alongside this pilot when the round was planned: the
  pilot's two largest measured effects (the duplicated-title passage and
  the length-normalization/`max_passages` interaction) are both authoring
  and configuration fixes inside the existing lexical architecture, and
  the one real vocabulary gap found already has a documented, adopted fix
  (`docs/authoring.md`'s FAQ-pair convention) that costs nothing in
  offline determinism or the citation guarantee. `docs/pilot-usagov.md`
  states the recommendation plainly: do not pursue semantic retrieval,
  citing this repository's own measured history of twenty-one reverted
  ranking configurations for the same reason.

#### Changed

- Every action in `ci.yml` is pinned to a full commit SHA with a version
  comment, matching what `pages.yml` already did. The SHAs are the exact
  commits the previous major-version tags resolved to, so nothing about what
  runs has changed; what has changed is that a moved tag can no longer change
  it.
- `pyproject.toml`: the dev extra now carries version floors (ruff, mypy,
  pytest, coverage) instead of bare names, and gains mypy, coverage, and
  complexity configuration.

#### Fixed

- `ci.yml`'s "Nothing above resolved the auditor" guard — meant to catch the
  answering engine importing the audit harness it must stay independent of —
  matched the bare substring `plumbline` anywhere in `cairn/*.py` and grew an
  exclusion list of allowed non-import mentions (`plumbline-bundle`,
  `plumbline.pin`, and so on) as legitimate references accumulated. The
  list never caught up: `./plumbline-gate.sh`, named in CLI help text added
  across three earlier PRs (`cairn/cli.py`, `cairn/record_diff.py`,
  `cairn/explain_diff.py`), was never added to it, and every one of those
  PRs merged with this job silently red — nothing enforced it, since no
  branch-protection ruleset is applied yet. The guard now matches what its
  own name says: an actual `import plumbline` or `from plumbline import`
  statement, anchored to the start of a line. This catches the real failure
  mode precisely and permanently, rather than adding one more string to an
  allow-list the next help-text mention will outrun again.

## 0.1.0 — 2026-08-16

First citable version. Everything the functional specification asks for is
implemented and measured, and what is not implemented is written down rather
than left to be discovered — see "What is still open" in
[DESIGN.md](DESIGN.md), where each entry is anchored to a test that fails if
the entry stops being accurate in either direction.

**The behaviour.** Answers are extractive: a grounded answer is a corpus
passage quoted verbatim with an inline citation, so every fact in it, numbers
included, appears character-for-character in a cited source. When no passage
clears the relevance threshold, Cairn refuses, cites nothing, points to a human
and exits 0 — a refusal is an outcome, not an error. Three languages, one of
them right-to-left, with direction derived from the language rather than
configured. When the only source is in another language, Cairn says so in the
language it was asked in and quotes the source untranslated, because
translating a policy amount would produce a number no document contains.

**The machinery for not being believed.** A committed evidence bundle recorded
from the real engine; an external auditor (Plumbline) pinned to an exact
commit, resolved at run time and never a dependency; a committed baseline, so a
score that decays without breaching a floor still fails; an operator explain
mode that attributes a bad answer to retrieval or to composition; and a
guard that fails on any suite silently disabled or any non-default floor with
no reason recorded.

**Runtime dependencies: none.** Standard library only, no model, no network.
The demo runs offline from a clean checkout.

Known limitations at this version, all measured and all written up: a
colloquially-phrased question that shares no words with the corpus is refused
(`ck-015`); one answer comes from the right document's wrong paragraph
(`ck-022`); cross-language retrieval needs the document's own name to survive
the crossing; the audit scores a correct cross-language answer as a failure and
has room for exactly one such item; the branch-protection ruleset is committed
and not applied, so the gate reports rather than blocks; and no manual
screen-reader session has happened.
