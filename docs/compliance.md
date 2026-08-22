# Compliance and procurement readiness

This page is for the audience the rest of the documentation is not written
for: a privacy officer, a security reviewer, or a procurement analyst
deciding whether Cairn is safe to bring in front of an intake committee —
not a developer deciding how to configure it. It summarizes what those
other documents already establish, in one place, in the order a compliance
review usually asks its questions, and adds the one thing nothing else in
this repository states plainly: what happens to data over time, and for
how long.

Nothing here is legal advice, and nothing here certifies compliance with
any specific regulation. It states facts about what the software does and
does not do; whether those facts satisfy your agency's obligations under
public-records law, a state privacy statute, or a federal requirement is a
determination your own counsel or compliance office has to make.

## What Cairn is, for a procurement record

Cairn is a self-hosted, open-source (Apache License 2.0) reference
implementation, not a commercial product or a SaaS subscription. There is
no vendor to contract with, no license fee, and no external service it
depends on to function — an agency that adopts it runs the software on
infrastructure it already controls. `README.md`'s Standards Conformance
table is the fullest single inventory of what the project claims and where
each claim is checked; this page draws from it rather than repeating it.

## Security posture

- **No third-party runtime dependencies.** The package that answers
  questions is standard-library Python only — nothing to audit in a
  dependency tree, nothing that resolves a package at runtime.
- **Local by default, exposed only on request.** `cairn serve` binds
  `127.0.0.1` and offers no authentication, TLS, or rate limiting unless an
  operator explicitly configures one of `--auth-token`, `--rate-limit`,
  `--cors-origin`, or `--allow-embed` — see `docs/deployment.md` and
  `docs/embedding.md`. A default installation is not reachable from a
  network at all.
- **Automated supply-chain scanning.** `gitleaks`, Semgrep, and `pip-audit`
  run on every change and on a schedule, and every third-party GitHub
  Action the project's own CI uses is pinned to a commit SHA rather than a
  movable tag.
- **A defined vulnerability-reporting channel with a stated response
  window.** `SECURITY.md` names a private reporting path and a seven-day
  acknowledgement expectation, and states plainly what is and is not in
  scope for a report — including project-specific failure modes (an
  ungrounded answer presented as grounded, corpus content leaked through a
  refusal) alongside the usual list.
- **A fail-closed evidence gate**, not self-reported test results: every
  change to what the software answers is graded by an external auditor
  pinned to an exact commit, and the gate exits non-zero rather than
  skipping if that auditor cannot be resolved. This is evidence of
  engineering rigor a security reviewer can point to, not a claim asking to
  be taken on faith.

## Data handling

Cairn's default behavior is documented, tested, and unconditional: nothing
about the questions people ask is ever logged. That default holds unless an
operator explicitly turns on one of two opt-in features, and the two are
different enough in kind that they need separate answers:

| What | Default | Opt-in |
|---|---|---|
| The corpus (an agency's own documents) | Stays on the operator's machine; never uploaded anywhere | N/A — always local |
| A question someone asks | Answered, then gone. No log, no database row, nothing written to disk | N/A — there is no flag that turns question logging on |
| Refusal analytics (`--refusal-stats`) | Off | An aggregate count per (language, reason) only — never a question, a client address, or a timestamp. See `docs/refusal-analytics.md`. |
| Follow-up requests (`--followup-store`) | Off | Real contact information a person submits themselves, plus their question only if they separately check a box on that one submission. See `docs/followup.md`. |

The distinction that matters for a privacy review: `--refusal-stats`
produces data that cannot be traced back to an individual by design —
counting "3 refusals in Spanish, below-threshold" carries no more
information after the fact than any other refusal with the same shape.
`--followup-store` is the opposite kind of thing on purpose: it exists to
capture a real person's contact information so staff can reach them, and
it is real personal data the moment an operator turns the flag on. Treat
a server running with `--followup-store` the same way you would treat any
other system that collects contact information from the public.

## Records retention

**Cairn enforces no retention period on any file it writes, for any
feature.** This is stated nowhere else in the documentation as plainly as
it needs to be for a compliance review, so it is stated here:

- The **index** (`.cairn/index.json`) is a derived artifact rebuilt from
  the corpus on demand. It carries whatever the corpus carries and nothing
  else; its retention is the corpus's retention, which is entirely the
  operator's to define.
- The **refusal-stats file**, if enabled, is a JSON object that grows by
  incrementing counters — it does not grow in size with traffic the way a
  log does, and there is nothing in it to purge that would change what it
  reveals about an individual. An agency may still choose to reset it
  periodically as a matter of policy; `cairn` has no command that does this
  for you — deleting the file and letting `cairn serve` recreate it is
  the whole procedure.
- The **follow-up store**, if enabled, is an append-only file of real
  contact information with **no automatic expiry, no automatic deletion,
  and no built-in retention schedule of any kind.** `docs/followup.md`
  frames removing a handled line as operational hygiene for staff working
  a queue; it is not a compliance control, and nothing enforces that
  removal happens. **If your agency operates under a public-records
  retention schedule, a data-minimization requirement, or any other rule
  that bounds how long personal contact information may be kept, your
  agency is responsible for implementing that bound** — a cron job, a
  script, a documented staff procedure — because Cairn does not implement
  one for you.
- The **evidence bundle** (`plumbline/bundle/`) is a development and audit
  artifact built from a committed, synthetic question set against the
  bundled demo corpus. It contains no data from a real deployment and is
  not something a live installation produces or updates on its own.

If your agency's compliance process requires a documented retention
schedule before a system can go live, `--followup-store` is the one piece
of this software that needs one written before it is turned on.

## Accessibility status

Cairn targets WCAG 2.2 AA as behavior, checked in two layers: `tests/test_ui.py`
verifies markup, semantics, and computed color contrast with no browser
involved, and `tests/browser/` drives the real served page in Chromium
through axe-core's WCAG 2.2 AA rule set, in light, dark, and right-to-left
presentations. Both layers run on every change and are pinned to exact tool
versions rather than a moving rule set — see DESIGN.md, "Two layers of
accessibility checking."

**The honest gap, named rather than hidden: no person has driven this page
with a screen reader.** Automated checks verify what markup and rendered
behavior can promise — roles, live-region politeness, focus never moving
unexpectedly, that an announcement actually fires. None of that is the
same as a real assistive-technology session, and this project states that
limitation in its own README table rather than letting an automated pass
rate stand in for it. A procurement review that requires a completed
manual accessibility audit (a VPAT, a real screen-reader walkthrough) should
treat that as outstanding work, not as already covered by what is here.

## Support and maintenance reality

Cairn is maintained by one person, unpaid, as a reference implementation —
not by a vendor with a support contract, an SLA, or an incident-response
team. `SECURITY.md` states a seven-day acknowledgement expectation for a
vulnerability report and asks that expectations be sized accordingly. This
matters for a procurement risk register the same way any other
single-maintainer open-source dependency does: an agency adopting Cairn is
taking on the same operational responsibility it would for any
self-hosted software with no paid support behind it — its own patching,
its own monitoring, its own incident response for anything Cairn itself
does not detect. Nothing here should be read as a claim of continuous
maintenance guaranteed into the future.

## Where the rest of the detail lives

This page summarizes; it does not replace the documents it draws from.

- [`SECURITY.md`](../SECURITY.md) — the full vulnerability-reporting
  process and scope.
- [`docs/deployment.md`](deployment.md) — what changes when a server
  moves past a single laptop.
- [`docs/embedding.md`](embedding.md) — CORS and iframe embedding, and
  their independent scopes.
- [`docs/refusal-analytics.md`](refusal-analytics.md) and
  [`docs/followup.md`](followup.md) — the two opt-in features with the
  most data-handling substance.
- [`README.md`](../README.md)'s Standards Conformance table — the fullest
  single inventory of what this project claims, against what checks it.
