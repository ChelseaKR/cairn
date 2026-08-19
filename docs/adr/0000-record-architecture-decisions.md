# 0000. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Chelsea Kelly-Reif

## Context

The reasoning behind this repository's design is already written down at
length. `DESIGN.md` argues the core stance, the retrieval threshold, the
explain mode, and what is still open. `README.md` argues the merge gate and
why grading a recording is not the same as grading the server. `WORKLOG.md`
records what happened and when.

None of that is a decision log. A prose document is edited in place, so the
version that justified a past choice disappears the moment the choice changes.
For a project whose whole argument is that its claims can be checked against
something, "the reasoning used to say something else and you cannot see what"
is the wrong shape.

What was missing is a form in which one decision can be cited, dated, and
superseded on its own.

## Decision

Architecture decisions are recorded in `docs/adr/` as Markdown files named
`NNNN-kebab-title.md`, numbered from 0000 and never renumbered. Each carries
Status, Date, Deciders, Context, Decision, and Consequences.

Status is one of `Proposed`, `Accepted`, `Superseded by NNNN`, or
`Deprecated`. An accepted record is not edited to say something different. It
is superseded by a later one that says what changed and why, and its own
Status line is updated to point at the successor. That is the only permitted
edit to an accepted record.

This log starts now rather than retroactively. The decisions already argued in
`DESIGN.md` are not being copied into ADRs to backfill a history that did not
exist: `DESIGN.md` remains the long-form argument, and a future ADR that
revisits one of its choices cites it. Backfilling would produce records dated
today for decisions made months ago, which is the same dishonesty in a
different file.

## Consequences

- A decision that changes something argued in `DESIGN.md` gets an ADR, and the
  ADR cites the section it changes rather than restating it.
- The log will be sparse at first, and sparse is the accurate report. An ADR
  log padded to look active is a log nobody can trust to be complete.
- Nothing enforces this mechanically. The numbering and the immutability rule
  are a convention, held by review.
