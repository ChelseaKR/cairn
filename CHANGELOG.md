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
tooling and repository documentation only.

#### Added

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
