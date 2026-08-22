# Security policy

Cairn is a reference implementation, not a service. There is no deployment to
attack: what ships is a standard-library Python package, a local HTTP server an
operator runs on their own machine, and a committed evidence bundle. The
runtime has no third-party dependencies and no model.

That shape moves where the risk actually lives, so this policy names it rather
than reciting a generic one.

## Reporting a vulnerability

Report privately through GitHub's
[private vulnerability reporting](https://github.com/ChelseaKR/cairn/security/advisories/new)
on this repository's Security tab. Please do not open a public issue for a
security problem.

Expect an acknowledgement within seven days. This is unpaid work by one
person, so please size your expectations accordingly, and please do not
disclose publicly until there is a fix.

## What counts as a vulnerability here

The usual list applies: code execution from input data, secret exposure,
supply-chain compromise. On top of it, three things specific to what this
project claims:

- **A grounded answer that is not grounded.** Cairn's entire contract is that
  it answers only from the operator's corpus and quotes it rather than
  paraphrasing. Any input that makes it emit text no source passage supports,
  or attach a citation to a passage that does not contain the quoted words, is
  a security bug in the sense that matters for a public agency answering
  constituents. It is not a cosmetic defect.
- **Corpus leakage through a refusal.** A refusal must not disclose what the
  corpus contains. A crafted question that turns "I have no source for that"
  into a description of documents the asker cannot otherwise see is in scope.
- **A path that makes the merge gate report green without grading.** The gate
  fails closed on purpose: if the pinned auditor cannot be resolved it exits
  non-zero rather than skipping. Any way to make it skip, pass without a
  resolved harness, or be graded by an unpinned one, is in scope. So is any
  way to make `cairn record` write a bundle that does not match what the
  engine produces.

## The server

`cairn serve` binds a loopback HTTP server for local use, with no
authentication, no TLS, and no rate limiting by default — and that default is
not intended to be exposed to a network. That is a documented boundary, not
an oversight, so "the default server has no auth" is not a report. A way to
reach it from off the host when it was told to bind loopback, or to escape
the corpus directory through a request path, is.

An operator who does need to expose it can opt into bearer-token auth and a
request-rate limit (`--auth-token`/`CAIRN_AUTH_TOKEN` and `--rate-limit`; see
`docs/deployment.md`). Both are off unless explicitly configured, so a report
against the *default* server about missing auth or rate limiting is still not
in scope — but a way to bypass a *configured* token check (other than trying
tokens), or to make a configured rate limit not apply, is.

The default also sends no CORS headers and refuses to be framed
(`frame-ancestors 'none'`). An operator can opt a named list of origins into
either, independently, for embedding in an agency's own site
(`--cors-origin`/`--allow-embed`; see `docs/embedding.md`). Both are
exact-origin allow-lists with no wildcard. A report that a *default* server
sends no `Access-Control-Allow-Origin` or refuses framing is not in scope —
but a way to get a CORS header or embed permission for an origin *not* on a
configured list, or a wildcard where none was configured, is.

The default also logs nothing about the questions people ask, and that is
unconditional — there is no flag that turns question logging on. The one
opt-in exception is `--refusal-stats`, which records an aggregate count per
(language, reason) pair on a refusal only, never the question, the client,
or a timestamp (see `docs/refusal-analytics.md`). A way to make a configured
`--refusal-stats` file carry anything beyond that — question text, a
client address, per-event data of any kind — is in scope; the absence of
the flag, or the aggregate counts it does produce by design, are not.

A second opt-in, `--followup-store`, is a deliberately different shape: it
exists specifically to capture a real person's own contact information on a
refusal, for a human handoff (see `docs/followup.md`). That is not a
question-logging leak — the asker submits it themselves, on a form that
states what happens to it, and nothing is ever contacted automatically.
What is in scope: a way to make `--followup-store` record a question
without that submission's own "include the question" box having been
checked; a way to reach `/follow-up` or get its contact data written
anywhere when `--followup-store` was never set; or a way to make the stored
question differ from what the asker actually submitted. The store file
containing real contact information at all, when an operator explicitly
configured the flag, is the feature working as designed, not a report —
protecting that file (permissions, backups, retention) is the operator's
responsibility for any file this server is told to write, the same as for
`--refusal-stats` or an operator's own `cairn.toml`.

## Out of scope

- The accuracy of documents an operator puts in the corpus. Cairn quotes what
  it is given; it does not fact-check it.
- The demo corpus, which is synthetic and says so.
- Denial of service against a server the reporter is running themselves.
