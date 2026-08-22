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

## Out of scope

- The accuracy of documents an operator puts in the corpus. Cairn quotes what
  it is given; it does not fact-check it.
- The demo corpus, which is synthetic and says so.
- Denial of service against a server the reporter is running themselves.
