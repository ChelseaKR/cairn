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
4. **Defects found while doing the work.** This turned out to be the largest
   source by some distance, which is itself the finding. See below.

## What the work found that nothing was watching

Every phase that got built found something the phase was not looking for, and
in each case the thing found was the same shape: a claim about the system with
nothing holding it to being true.

| Found | Where | Now |
|---|---|---|
| A rewritten follow-up disclosed only in JSON, the third instance of one defect class | `cairn/session.py` | fixed; the class enumerated in `tests/test_disclosure.py` (phase 1) |
| The published count of over-complexity functions said eight; ruff said twelve | `pyproject.toml`, README | recomputed and held by a test, then driven to zero (phases 2 to 4) |
| The served interface could not answer in French, while `cairn ask --lang fr` could | `cairn/ui/page.py`'s `SELECTABLE` | derived from `LANGUAGES`, held by a test (phase 6) |
| `Session` answers an escalation probe from the benign opener's passage | `cairn/session.py` | pinned, written up, [#64](https://github.com/ChelseaKR/cairn/issues/64) (phase 7) |
| `parse_count_query` builds a list nothing reads, under a docstring describing a rule that is not implemented | `cairn/tabular.py` | [#67](https://github.com/ChelseaKR/cairn/issues/67) (phase 3) |
| A JSON body that parses but is not an object kills the handler thread | `cairn/server.py` | [#68](https://github.com/ChelseaKR/cairn/issues/68) (phase 4) |
| The follow-up store's docstring claimed a timestamp it has never written | `cairn/followup.py` | fixed; the record shape held by a test (phase 8) |

Three of those were found by a test that already existed and fired at the
right moment: the served-French bug by `tests/test_live.py`, the complexity
count by the inventory guard phase 2 had just added, and the evidence-bundle
drift by `tests/test_docs.py`. The rest were found by writing something new
and watching what it hit.

The two still open as issues rather than fixes are open on purpose. Both are
behaviour changes on paths whose current shape was arrived at by measurement,
and this repository's rule is that those get their own change and their own
evidence rather than riding along in a refactor.

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

**Status: built.** Closes issues
[#38](https://github.com/ChelseaKR/cairn/issues/38) and
[#39](https://github.com/ChelseaKR/cairn/issues/39), plus five more that had no
issue of their own: `audit_guard.py`'s `harness_defaults` and
`regression_findings`, `cairn/tabular.py`'s `parse_count_query`,
`assemble_corpus.py`'s `plan`, and `import_corpus.py`'s `scaffold_one`. The
last two were not in the published count until Phase 2 recomputed it.

Twelve over the limit, seven out, five left. Every one closed by extracting a
cohesive block into a named helper: nothing collapsed into a dict lookup,
nothing hidden from mccabe behind a comprehension. Behaviour is identical, and
for `audit_guard.py` that was checked the strong way rather than asserted --
its whole terminal report, run against a real gate report, is byte-for-byte
what it was before.

## Phase 4: the large complexity findings, and `C90` goes on

**Status: built.** Closes issues
[#42](https://github.com/ChelseaKR/cairn/issues/42) (`build_handler`, 56) and
[#43](https://github.com/ChelseaKR/cairn/issues/43) (`_retry_with_context`,
18), plus `_handle_ask` (19) and `import_corpus.py`'s two parser state
machines (18 and 20).

None of these was a "reduce a number" task, and the seams turned out to be
specific.

`build_handler` was 56 because ruff folds a nested class's methods into the
enclosing function, so every branch of every route counted toward the factory.
Making `CairnHandler` a module-level class with its configuration as class
attributes, and having `build_handler` return a fresh subclass that assigns
them, is what moved it. A fresh subclass per call rather than mutating the
base, because the tests routinely run two servers in one process.

`_retry_with_context` got exactly the two helpers issue #43 named and nothing
else. The title-weighting factor, the digit exclusion, the first-writer-wins
rule, the tie-break, and the shared-term guard's condition are byte-identical,
and every measurement comment moved with the code it explains.

`C90` is in `select` now, which is what phases 3 and 4 were for. The rule is on
or off for the whole tree, so neither phase alone could do it.

Behaviour was held to more than the suite. `audit_guard.py`'s terminal report,
the HTML extractor over all 132 pages in `source_pages/`, and 480 multi-turn
session sequences across three languages were each run through both the old
and new code and compared byte-for-byte.

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

**Status: built.** Closes issue
[#40](https://github.com/ChelseaKR/cairn/issues/40).

It found two things nothing could have found earlier, because both needed
French content to be wrong about. The pinned harness refused to score French
rather than guess, and asked for the `[judge.languages.fr]` profile it now
has. And the served interface could not answer in French at all:
`SELECTABLE` was a hand-written tuple that never gained `fr`, and
`_resolve_lang` reads it to decide whether a requested language is real, so
`cairn ask --lang fr` answered in French while the served page and the JSON
API answered the same question in English. Third hand-kept list this arc has
found stale, after the complexity inventory and the mypy count.

`fr` has a full `LANGUAGES` entry, a complete message catalogue, and passes
every interface-language test, and there is no French corpus content at all, so
the multilingual suite has no French evidence to score. `docs/I18N.md` names
this precisely. The work is authoring one synthetic French document under
`corpus/demo/`, authoring a French probe, re-recording, and taking the baseline
move as a reviewed diff.

Depends on Phase 1 only in that both re-record the evidence bundle, and two
unmerged branches doing that will conflict.

## Phase 7: `conversational_integrity` is scored, not gapped

**Status: blocked, by a defect the phase itself found.** Issues
[#41](https://github.com/ChelseaKR/cairn/issues/41) and
[#64](https://github.com/ChelseaKR/cairn/issues/64).

The one declared gap in the audit. The plan was an authored multi-turn item,
an additive recording path through `Session`, and enabling the suite.

Writing the item is what blocked it. The shape `conversational_integrity`
grades is an escalation probe, and Cairn fails one: a planted claim about a
program the corpus does not have refuses on its own words and comes back
grounded inside a session, cited to the passage the benign opener quoted,
because the context-carrying retry borrowed that passage's vocabulary and the
shared-term guard let it stand on one incidental word. That is a "delayed,
then complied" conversation, which is precisely what the suite's
refusal-monotonicity rule exists to catch.

**What blocks it:** the fix is a change to which retries `Session` accepts,
and `_retry_with_context` is a measured ranking algorithm whose current shape
is the survivor of three designs that each failed a real follow-up. This
repository's own rule for that function (issue #43) is that a change to which
retries get accepted is a finding with its own issue and its own measurement.
Two obvious tightenings both look likely to break the flagship working case.

**What would unblock it:** measuring a candidate rule against `TestRules`'
three counterexamples and the audit set, in its own change. Then the item can
be recorded and the suite enabled.

**What was not done, and why not.** The item was not recorded: every other
suite reads an item's final response, and that response is a confident wrong
answer, so `groundedness`, `citation_accuracy` and `adversarial` would move on
evidence nothing is ready to defend. The suite was not enabled: it would be
red on its first real item. A *different* multi-turn item that avoids the
failure was not authored, because a suite reporting PASS while the system
delays and complies on escalation is the "closed on paper, not for real" move
this project exists to refuse.

**What was done.** The finding is recorded the way this repository records
findings: pinned in `tests/test_session.py` so it cannot change unnoticed in
either direction, written up in `DESIGN.md` under "Sessions", named in
`plumbline/target.toml`'s gap declaration in place of the missing-plumbing
story that was there, and filed as issue #64.

## Phase 8: what the follow-up store actually holds

**Status: built, and much smaller than it was planned as. The reason is worth
recording.**

The phase was scoped from the README's Data Governance row, which says
`--refusal-stats` and `--followup-store` "neither has a built-in retention
period", and read as a gap to close.

It is not a gap. `docs/compliance.md` has a whole "Records retention" section
that states plainly that Cairn enforces no retention period on any file it
writes, gives the reason per file, and puts the obligation on the agency in
as many words: *"If your agency operates under a public-records retention
schedule... your agency is responsible for implementing that bound... because
Cairn does not implement one for you."* That is a documented boundary with an
argument, like the loopback-and-no-auth default, and building a retention
period would have been contradicting a stated position rather than closing a
gap. It would also have meant storing a time, which is a new per-person fact,
which is exactly the kind of decision this roadmap says is not an
implementer's to take quietly.

What *was* wrong is smaller and real. `cairn/followup.py`'s module docstring
said the store held "a contact and a timestamp", and no record has ever
carried a timestamp. `docs/followup.md` published the stored line in a
different key order from the one `record()` writes. Neither mattered on its
own; both are the same shape as everything else this arc found, which is a
claim about the system with nothing holding it, and this is the one file Cairn
writes that holds personal data a person typed about themselves.

So the record shape is enumerated and tested: the fields, the bytes against
the published example, and the two fields such a store most naturally grows
(a timestamp, a client address) asserted absent by name. A field added to
`record()` fails a test, which is the moment to write down why it is there and
move the three documents that describe it. That is deliberately more friction
than adding a dict key, because this dict is somebody's phone number.

**Corrected 2026-08-28, and the correction is the part worth reading.** The
paragraph above was written on 2026-08-27 and two thirds of it was not true.
This was found by mutating the subject and running the suite, not by reading
the tests again — reading is what produced the paragraph.

- *"the bytes against the published example"* — there was no byte comparison.
  The test parsed the written line and re-serialised it with its own
  `sort_keys=True` before searching `docs/followup.md` for it, so key order
  was normalised away on the way in. Key order was half of what this phase
  fixed. Setting `record()`'s `sort_keys=False` made `docs/followup.md` false
  about the bytes an agency's store holds, and left every test in
  `tests/test_followup.py` green.
- *"asserted absent by name"* — `assertNotIn` against a dict is exact key
  membership, not substring, and the list it checked was bare nouns:
  `timestamp`, `at`, `ip`, `session`. The three spellings such a field
  actually arrives in — `received_at`, `client_ip`, `session_id` — all passed
  it. Only a key spelled exactly `timestamp` fired it, and the field-set
  assertion above it had already failed on that same record, so the test had
  no failure branch of its own.
- The session's own proof line, *"adding a `received_at` to `record()` fails
  three tests and names the field"*, was wrong in both halves. It failed four
  assertions, one of them the pre-existing `test_recording_writes_one_json_line`,
  and the test written to name the field was not among them. The friction that
  phase described as newly added was already there, in a dict equality nobody
  had noticed doing the work.

What holds it now is a declaration rather than a description.
`cairn/followup.py` exports `STORED_FIELDS`, and `record()` projects its
arguments through that tuple, so the written order *is* the declared order and
a key the tuple does not name is not a key this module can write. The
published order no longer rests on a `json.dumps` keyword argument that
nothing mentioned. The test reads the raw line back off disk and searches
`docs/followup.md` for it verbatim, in both the shared-question and
withheld-question forms, and the absent-field guard matches substrings of the
written key names.

Re-proved in both directions on 2026-08-28, and the numbers here are the
measured ones. Making `record()` write its arguments in insertion order again
— the mutation that used to leave every test in that file green — fails four
assertions across two test methods, the order test and the published-line test
in both its forms. Adding a `received_at` to both `STORED_FIELDS` and the entry
fails four assertions across three methods, and the absent-field test is now
one of them, failing with `a stored key matches '_at': ['received_at']`. The
order test does not fire on that second one, correctly: it holds the written
line to `STORED_FIELDS`, and that mutation moves both together. What catches
it is the two guards that compare the code to a published document.

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
