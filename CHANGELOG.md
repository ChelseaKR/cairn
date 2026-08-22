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
