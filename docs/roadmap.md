# Roadmap

A two-to-three year arc for this repository, written down so that "what is
next" is checkable rather than remembered.

Three rules govern this page, and they are the reason it is worth having.

**Nothing here is a promise.** A phase is a piece of work someone has thought
about, sized, and put in an order. It is not a commitment to a date, and this
project has no users to make dates for. Phases move, and a phase that is
dropped gets a line saying it was dropped and why, rather than disappearing.

**Status is the whole point.** Every phase carries `built`, `open`, or
`blocked`. `blocked` names what blocks it and what would unblock it. A phase
cannot be marked `built` while any part of it is a stub, a placeholder, a dead
configuration key, or a marker for later, because that is the failure mode the
rest of this repository argues against, arriving one document over.

**Work that was considered and refused is not a gap.** The last section lists
things a reader could reasonably expect to find here and will not, with the
reason and the place the reason is argued. `DESIGN.md` has measured and
rejected several of them at length; a roadmap that quietly re-proposes them
would be throwing that measurement away.

## Where the work comes from

Four sources, in descending order of how much weight they carry:

1. **`DESIGN.md`'s "What is still open"** and the deferred items scattered
   through it. These are the author's own account of what a reader will not
   find, and they come with the reasons.
2. **The README's Standards Conformance table.** Three of its rows are gaps
   stated as gaps. A phase that closes one of them changes a row from an
   admission to a result.
3. **The open issues.** Twelve of them, most labelled `good first issue`,
   several with the fix already reasoned out in the issue body.
4. **Defects found while doing the work.** Two of the phases below exist
   because something turned up mid-change that nothing was watching.

## Phase 1: a disclosure is not made until a person can read it

**Status: built.** See [ADR 0001](adr/0001-a-disclosure-is-not-made-until-a-person-can-read-it.md).

Three defects in this repository have been the same defect: a disclosure that
existed as a field and not as a sentence. `Answer.cited_text` dropped the
cross-language notice; the structured-table path crossed languages with
`AskResult.cross_language` already returning `True` and no notice; and
`Session` rewrote an elliptical follow-up, recorded `resolved_with_context` in
the served JSON, and printed nothing about it anywhere a person reads.

Each was found by somebody reading the code. `DESIGN.md` says of the first one:
"It was fixed by reading the code. The next one will not be." Phase 1 is that
sentence made mechanical. `tests/test_disclosure.py` enumerates the disclosures
out of the message catalogue and the surfaces out of the modules that ship
them, and checks the cross product, so a fourth instance fails a test instead
of waiting for a reader.

It also fixes the third defect, which was live when the phase started.

## Phase 2: `mypy --strict` reports zero, and runs

**Status: built.** Closes issues
[#34](https://github.com/ChelseaKR/cairn/issues/34),
[#35](https://github.com/ChelseaKR/cairn/issues/35),
[#36](https://github.com/ChelseaKR/cairn/issues/36),
[#37](https://github.com/ChelseaKR/cairn/issues/37).

Strict mode reported 44 findings. `pyproject.toml` said so at the point of
configuration and the README's Code Quality row said so in public, which is the
honest handling of a gap and not a substitute for closing it. The findings were
mechanical: a missing return type, a bare `dict` needing type arguments, one
import taken through a module that does not re-export it.

The deliverable was never "fewer findings". A tree that reports zero with the
check switched off reports one on the next pull request and nothing says so, so
`make verify` now runs strict mode and the gate is the guard. There are no
per-module overrides, and a test holds that: a strict gate with an excused
module is a strict-looking gate.

Turning the check on is a change to what every contributor's gate demands, and
it is one line to revert if the maintainer would rather have zero findings
unenforced. The argument for running it is in `pyproject.toml` beside the
setting.

The same phase found the *other* half of that conformance row was simply wrong.
`pyproject.toml` named eight functions over the complexity limit, one at a time
with a number each; ruff reported twelve. Four arrived with the pilot tooling
and nothing recompiled a hand-kept list. The inventory moved into
`tests/test_code_quality.py`, where ruff confirms it.

## Phase 3: the small complexity findings

**Status: open.** Issues [#38](https://github.com/ChelseaKR/cairn/issues/38),
[#39](https://github.com/ChelseaKR/cairn/issues/39), plus six more with no
issue of their own: `audit_guard.py`'s `harness_defaults` and
`regression_findings`, `cairn/tabular.py`'s `parse_count_query`,
`assemble_corpus.py`'s `plan`, and `import_corpus.py`'s `handle_starttag`,
`handle_endtag` and `scaffold_one`. The last four were not in the published
count until Phase 2 recomputed it.

Each is 11 against a configured limit of 10, and each is presentation or
orchestration code with comprehensive tests already watching its output. The
constraint is that behaviour stays identical, which for `render_terminal` means
byte-identical.

## Phase 4: the two large complexity findings

**Status: open.** Issues [#42](https://github.com/ChelseaKR/cairn/issues/42)
(`build_handler`, 56) and [#43](https://github.com/ChelseaKR/cairn/issues/43)
(`_retry_with_context`, 18).

Neither is a "reduce a number" task. `build_handler` is a closure factory that
four features' worth of branching landed in because it was the least-friction
place at the time; the work is finding the right shape for a handler that now
genuinely routes, gates, negotiates format, and dispatches between table,
stream, session and plain answers. `_retry_with_context` carries a measured
ranking algorithm whose comments document three designs that were tried and
failed, so a reshuffle that changes which term wins a close tie is a finding,
not a cleanup.

Phases 3 and 4 together are what would let `C90` into `pyproject.toml`'s
`select`. Neither alone does: the rule is on or off for the whole tree.

## Phase 5: a hand-written merge cannot silently drop a field

**Status: built.** Closes issue
[#51](https://github.com/ChelseaKR/cairn/issues/51).

`split_intents` merges `RetrievalTrace` and `Candidate` field by field. Every
field on both carries a default, so a field the merge forgets falls back to the
default rather than raising. Two bugs have already been instances of exactly
that: `query_terms` in #46, and `matched`/`scoped`/`excluded` in #49. Both were
found by tracing explain-mode output by hand.

This is the same shape as Phase 1 one layer down, and the repository already
had the pattern: `tests/test_config_report.py` holds `diff_from_defaults` to
`fields(Config)` so a new config key cannot be silently ignored.

The issue offered two options and named (a), a field-coverage test, as the
smaller. It was built with a second half the issue did not ask for: every field
is not only *named* but *recomputed* independently from the part traces and
compared, because a table of names catches a field nobody handled and would
not catch a field handled wrongly, which is what both prior bugs actually
were. It also asserts the premise the merge's own comment states and nothing
checked, that every part scans the same index so `scoped` and `excluded` are
identical across parts rather than additive.

## Phase 6: French has corpus content, so the audit can score it

**Status: open.** Issue [#40](https://github.com/ChelseaKR/cairn/issues/40).

`fr` has a full `LANGUAGES` entry, a complete message catalogue, and passes
every interface-language test, and there is no French corpus content at all, so
the multilingual suite has no French evidence to score. `docs/I18N.md` names
this precisely. The work is authoring one synthetic French document under
`corpus/demo/`, authoring a French probe, re-recording, and taking the baseline
move as a reviewed diff.

Depends on Phase 1 only in that both re-record the evidence bundle, and two
unmerged branches doing that will conflict.

## Phase 7: `conversational_integrity` is scored, not gapped

**Status: open.** Issue [#41](https://github.com/ChelseaKR/cairn/issues/41).

The one declared gap in the audit. `Session.ask()` is real and tested, and
`cairn record` still builds every audited item through the plain `ask()`, one
call per question, so no item in the committed bundle has ever carried more
than one turn. `DESIGN.md` is explicit that this gap is this repository's to
close and that half of it landing did not close it.

The work is an authored multi-turn item, an additive recording path through
`Session`, enabling the suite in both audit configs, and the documentation that
currently says the gap is open.

Depends on Phase 1: a multi-turn item's recorded `cited_text` now carries the
context notice, so recording one before Phase 1 landed would record a
conversation that does not disclose itself.

## Phase 8: the two stores that hold data have a retention story

**Status: open.** No issue.

The README's Data Governance row says it: `--refusal-stats` and
`--followup-store` are the two opt-in features that hold data past the
no-storage default, and "neither has a built-in retention period". The refusal
counter is structurally incapable of holding a question, so its exposure is
bounded by shape; the follow-up store holds real contact information given by
consent, and its exposure is bounded by nothing.

## Phase 9: a person drives the page with a screen reader

**Status: blocked, and not on anything an agent can supply.**

`docs/screen-reader-test-script.md` is a task-by-task script for the session.
The script is not the session. The README says so in as many words, and
`DESIGN.md` gates further interactive surface on it having happened.

**What would unblock it:** a person with VoiceOver or NVDA working through the
script and writing up what it was like. No automated check substitutes, and
this repository's own documentation refuses to let one try.

## Phase 10: signed tags

**Status: blocked, and correctly so.**

The README's Release and Versioning row names this as its only gap. Closing it
needs a signing key that belongs to a person and a tag pushed to the remote.

**What would unblock it:** the maintainer generating or nominating a signing
key and cutting the tag. `CHANGELOG.md` already records that "the annotated tag
is cut by the maintainer afterwards, because tagging is a push and this
repository's working rule is that an agent does not push."

## Phase 11: the California pilot's county layer

**Status: blocked on licences and a decision.**

`WORKLOG.md` session 17 records what happened: Los Angeles County reserves all
rights and grants no licence, Fresno County prohibits re-use and mirroring
without written permission in those words, and Siskiyou's host refuses every
non-browser connection so its terms cannot be read. The county layer is the
layer that makes the pilot a deployment statement, and it cannot be committed
from either readable county.

**What would unblock it:** written permission from a county, or a county whose
terms permit it, or the maintainer choosing one of the three ways forward
already written down. All three are the owner's call, and none is a coding
task.

## Phase 12: upstream declarations the audit needs

**Status: blocked upstream, and this is a report to file, not work to do here.**

Two audit limitations have the same shape and the same fix, and the fix is in
Plumbline rather than here: an item-level declaration that a response is
*expected* to be in a different language from the question, and the same
mechanism for a response that is partly the target's own voice. Without the
first, `multilingual` scores a correct cross-language answer 0.0000 and the
evidence set has a one-item ceiling. Without the second, an answered table-tool
item cannot ship, because the notice is Cairn speaking and a lexical support
metric marks it unsupported.

**What would unblock it:** the declaration existing in Plumbline. Cairn
consumes Plumbline at a pin and pushes nothing to it, which `DESIGN.md` states
as a boundary in three places. Filing the report is in scope; making the change
here is not.

## Deliberately not on this roadmap

These are the things a reader might expect and will not find, with the reason
and where it is argued at length.

| Not planned | Why |
|---|---|
| A generative mode | `DESIGN.md` permits one as a clearly separated, off-by-default option and none is implemented. Anything generative would have to keep the "every fact appears in a cited passage" invariant that is currently structural, and the offline guarantee that is currently absolute. Not a roadmap item until somebody argues both, in an ADR. |
| Translating corpus content | A translated policy amount is an unsourced policy amount. Argued in `DESIGN.md` and enforced by composition being extractive. |
| BM25, document aliases, section-heading weights, a query-coverage factor, query-side diacritic folding, pseudo-relevance refusal rescue, a nonzero default `dense_weight` | Every one was built, measured against the audit set, and reverted, and `DESIGN.md` publishes the numbers. They share a reason: each turns a visible refusal into an invisible wrong answer, which is the trade this project exists to refuse. |
| A stopword list | The tokenizer exists to work without one. The alternative for `ck-022` is a corpus large enough for document frequency to mean something, which is not what a demo corpus is. |
| An inverted index, or precomputed passage norms | Sketched in `DESIGN.md` and deliberately not built, because nothing in this project's corpus or audited evidence needs it. The precondition is a deployment whose corpus reaches the low thousands of documents. |
| Answering `ck-015` | Every scorer-side fix was measured and rejected. `DESIGN.md`'s conclusion is that the fix is a corpus a plain reader recognizes, not a scorer, and that is a corpus decision. |
| Keyboard shortcuts, an in-page explain toggle, a corpus-browsing page | Gated on Phase 9 by this project's own stated priority. |
| A model-based audit judge | A gate that reaches the network is not a gate. |
