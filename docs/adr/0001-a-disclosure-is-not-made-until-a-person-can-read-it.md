# 0001. A disclosure is not made until a person can read it

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** Chelsea Kelly-Reif

## Context

Cairn says three things in its own voice, above the passages it quotes: that
the only source is in another language, that a number was counted rather than
quoted, and now that a follow-up was answered against an earlier question. Each
of those is also represented as machine-readable state: `AskResult.
cross_language`, `AskResult.tool`, `TurnResult.resolved_with_context`.

Three defects in this repository have been the same defect, and it is the gap
between those two representations.

`Answer.cited_text` was composed without the notice, so every client with one
channel and no sources list - a terminal, a transcript, the evidence bundle -
received a foreign-language passage with nothing saying why. `DESIGN.md`
records that it "lived through a milestone, and no run of the gate could have
found it", and then commits to something: "It was fixed by reading the code.
The next one will not be."

The next one was. The structured-table path bound tables without filtering by
language and returned before the notice logic, so a Spanish question was
answered from an English-only table in silence. `cross_language` was returning
`True` on that path the whole time. The machine-readable half was never wrong.

The third was live when this decision was made. `Session` resolves an
elliptical follow-up by rewriting the question with terms borrowed from what a
previous turn cited. It records `resolved_with_context` and `context_terms`,
the server puts both in its JSON response, and no rendering surface reads
either. `cairn chat` printed an answer to a question the person had not typed
and showed no sign of having done so.

Every one of these was found by a person reading the code. The per-feature
tests were green through all three, and they were right to be: a test that
knows about the cross-language notice cannot notice that a different notice is
missing, and a test that checks one surface cannot notice that a fourth surface
exists.

## Decision

A disclosure is not made until a person can read it, and that is enforced
structurally rather than remembered per feature.

**One channel.** Everything Cairn says about an answer goes in
`Answer.notice`. Not a field on a result wrapper, not a key the JSON payload
carries alone: the notice is the single string every surface that renders an
answer already reads, so a new disclosure reaches the terminal, the transcript,
the stream and `cited_text` by construction rather than by four separate
edits. `Session` therefore writes its disclosure onto the answer, and
`TurnResult` keeps its fields as the operator-facing half.

**One naming rule.** A message key carrying `_notice` in its name is Cairn
speaking about the answer below it. The name is the whole rule.

**One test that knows both sets.** `tests/test_disclosure.py` reads the
disclosures out of `cairn.messages` and holds the surfaces as real renderers
imported from the modules that ship them, and checks the cross product. Adding
a fifth `_notice` key without a scenario fails it. Adding a field to
`AskResult` or `TurnResult` without recording whether a reader needs to be told
fails it. Dropping the notice from any one surface fails it, per surface, by
name.

**Disclosures name what a reader can act on.** The session notice names the
earlier question rather than the borrowed terms, because the terms are what the
index stores and what the index stores is truncation-stemmed. The first draft
offered a reader "per, recei, allow" as the words it had searched with, two of
which are not words. A disclosure a reader cannot act on is decoration.

## Consequences

- The parity test is a second place to edit when a disclosure is added. That is
  the intent: the edit is the moment the question "where does a person read
  this" gets asked.
- The catalogue is the source of truth for what Cairn says, which makes the
  `_notice` suffix load-bearing. A disclosure added under a name without it
  would not be caught. That is a convention held by review, like ADR
  numbering, and it is written in `cairn/messages.py` where the keys are.
- Adding a message key changes the served page, because the page embeds the
  catalogue, which changes the interface snapshot in the evidence bundle and
  therefore the bundle hash. This decision makes that a recurring cost.
  `tests/test_live.py` catches it every time, which is how the same
  consequence was caught when `table_count_notice` was added.
- The session's disclosure changes what a multi-turn item would record. Nothing
  records one today, so no committed evidence moved; when
  `conversational_integrity` gets its evidence, it gets it from an engine that
  discloses.
- Four surfaces are enumerated. A fifth added later is not automatically
  covered, and the test cannot know about a renderer nobody told it about. The
  honest bound is that this catches every disclosure across every surface
  someone has written down, which is strictly more than the zero it was.
