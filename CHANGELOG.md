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

Nothing here changes what Cairn answers or how it is graded. Development
tooling, repository documentation, and one new read-only operator command.

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

#### Changed

- Every action in `ci.yml` is pinned to a full commit SHA with a version
  comment, matching what `pages.yml` already did. The SHAs are the exact
  commits the previous major-version tags resolved to, so nothing about what
  runs has changed; what has changed is that a moved tag can no longer change
  it.
- `pyproject.toml`: the dev extra now carries version floors (ruff, mypy,
  pytest, coverage) instead of bare names, and gains mypy, coverage, and
  complexity configuration.

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
