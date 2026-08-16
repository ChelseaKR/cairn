# Cairn

Retrieval-grounded question answering for public agencies, as a reference
implementation: it answers **only** from a corpus the operator supplies, shows
its sources on every answer, and when no source clears the relevance threshold
it refuses plainly and points to a human — no guessing, ever. A cairn marks a
verified trail; where there are no stones, there is no trail.

**Status: pre-release.** Every capability in the specification is implemented:
ingest with idempotent indexing, grounded answers with citations, refusal as a
first-class outcome, an operator explain mode that diagnoses a bad answer to
the right stage, three languages including right-to-left, an accessible chat
interface, and a fail-closed CI audit gate against a pinned external auditor —
run against the committed evidence and, separately, against the running
server. 255 tests plus 49 browser behaviour checks, standard library only,
offline.
This is a demonstration of correct behavior, not a production service.

Start here: **[the walkthrough](docs/demo.md)** — every command on that page is
executed by the test suite, so its output is what you will get.

## Provenance

- Built from a **functional specification** (idea-level requirements only — no
  code, wording, or constants were supplied). All naming, architecture,
  expression, and constants originate in this repository; see
  [DESIGN.md](DESIGN.md) for the decisions and their reasons, and
  [WORKLOG.md](WORKLOG.md) for the dated session log.
- Started **2026-08-15**. The git history is the build history: incremental,
  honestly dated, beginning with the design document.
- Implemented with **AI agents** working from the specification.
- License: **Apache-2.0**.

## Quick start (offline, no install)

Requires Python 3.11+. The runtime is standard-library only, so from a clean
checkout — with no network, no API key, no external model — the demo runs
directly:

```console
$ python3 -m cairn index
Indexed 40 passages from 10 documents (10 marked synthetic) in 3 languages [ar, en, es] -> .cairn/index.json

$ python3 -m cairn ask "How much unpaid rent does the housing relief grant cover?"
## How much the grant covers
The grant covers up to $3,500 of unpaid rent. ...

Sources:
  [1] Harbor Housing Relief Grant (housing-relief-en#2)
  [2] Harbor Housing Relief Grant (housing-relief-en#1)

$ python3 -m cairn ask "Can you help me renew my drivers license?"
I don't have a source for that. None of the official documents this assistant
is allowed to answer from cover your question, and I won't guess.
For help from a person, contact ...
```

Answers are extractive — composed verbatim from the retrieved passages — so
every fact in an answer, numbers included, appears character-for-character in a
cited source. Identical corpus + configuration + question always yields
identical output. Refusals carry no sources and exit 0: refusing without
evidence is correct behavior, not an error.

`pip install -e .` additionally gives you the `cairn` console command;
`--json` on `ask` emits a machine-readable record.

## Explaining a bad answer

`ask --explain` prints an operator trace above the answer: every candidate
passage with its score and its accept/reject verdict at the threshold, then a
verdict for each stage that could have gone wrong.

```console
$ python3 -m cairn ask --explain "What vaccinations does my dog need?"
Threshold: 0.165 (retrieval.threshold)
...
Attempt 1 (restricted to 'en'): 16 passages scored, 24 excluded, 4 candidates
  question terms:      does, dog, need, vacci, what
  in no passage:       does, dog, vacci
   1  0.069  reject  grocery-allowance-en#3  [en] Fresh Start Grocery Allowance
          matched 1/5: need
   ...
Stage 1 - retrieval: FAILED (below-threshold)
  4 candidates were scored and none cleared the 0.165 threshold. The best,
  grocery-allowance-en#3, scored 0.069 and was short by 0.096 on 1 of 5
  question terms (need). No passage searched contained does, dog, vacci —
  that part of the question is a corpus coverage gap, not a threshold setting.
Stage 2 - answer: NOT REACHED (no-evidence)
  The answer stage was handed no passages, so it refused. ...

Verdict: NOT GROUNDED - refusal, no sources.
Diagnose at: retrieval.
```

The point is the last line. A wrong answer whose retrieval stage passed is a
different bug from one whose retrieval stage failed, and the trace says which
you have — including the case where the right passage cleared the threshold and
was then dropped from the answer by `retrieval.max_passages`. The term lines
say *why* a score is what it is: which of the question's words each passage
actually held, which the corpus has never seen (a coverage gap), and which
were suppressed as too common (a scorer decision). Add `--json` for the same
trace machine-readably. Explain mode never changes the answer.

## Three languages, one of them right to left

```console
$ python3 -m cairn ask "Cuanto cubre la subvencion de alivio de vivienda?"
## Cuánto cubre la subvención
La subvención cubre hasta $3,500 de alquiler no pagado. ...

Fuentes:
  [1] Subvención de Alivio de Vivienda de Harbor (housing-relief-es#2)
```

A question is answered in the language it was asked in, from sources in that
language, and `--lang` states the language outright when you would rather not
rely on detection. Arabic is right-to-left in the way that matters: direction
comes from the language code, and Latin runs inside an Arabic line — passage
ids, phone numbers — are wrapped in Unicode bidi isolates so a terminal or a
browser does not reorder them.

Corpus coverage is deliberately uneven, because real agencies' translations
lag. Ask in Spanish about a document that exists only in English and Cairn
says so, in Spanish, and then quotes the English exactly as published:

```console
$ python3 -m cairn ask --lang es "How much does the GoPass cost per year?"
La única fuente que tengo para esto está escrita en otro idioma (English).
Se cita a continuación tal como fue publicada.
...
```

It does not translate the source. A translated policy amount is an unsourced
policy amount. Set `[language] cross_language_fallback = false` to refuse
instead.

**How far that reaches, measured rather than promised.** The fallback is
lexical, so it fires only when the question contains words the document
contains — and across languages the only words that survive are proper nouns
and numbers. `GoPass كم سعرها؟` is answered from the English document, in
Arabic, with the English quoted untranslated: the fallback crosses scripts
perfectly well. `¿Cuánto cuesta el GoPass por año?` refuses, in the same
script. What decides it is whether the program is named, which puts the
limitation on the person least likely to know its official name.
[DESIGN.md](DESIGN.md#what-is-still-open) carries the four measurements and
why the available bridge — letting a document declare its name in another
language — is refused.

## The demo corpus is synthetic

The bundled corpus under [`corpus/demo/`](corpus/demo/) is **entirely
fictional**: an invented agency, invented programs, invented amounts and
deadlines, in English, Spanish, and Arabic, each file marked `synthetic: true`. See
[its README](corpus/demo/README.md). Point `[corpus] path` in
[`cairn.toml`](cairn.toml) at your own directory of front-matter markdown
documents to use real content — swapping the corpus is a config change, never
a code change.

## The chat interface

```console
$ python3 -m cairn serve
cairn: serving the chat interface on http://127.0.0.1:8765/  (ctrl-c to stop)
```

Localhost only, no external resource of any kind, and a content security
policy of `default-src 'none'` so the browser enforces that rather than this
README claiming it. It targets WCAG 2.2 AA as behavior, not as attributes: a
skip link that lands in the question box, a transcript announced politely that
never steals focus, a separate assertive channel that carries errors and
nothing else, a labelled input with the Enter/Shift-Enter behavior written
under it, a permanent disclosure with no dismiss control, a language selector
that mirrors the whole layout for Arabic, a visible focus ring at every stop,
and light and dark presentations whose every colour pair passes AA. It answers
without JavaScript, too — the form posts and the server renders.

**No person has driven this page with a screen reader.** The browser checks
verify the plumbing one depends on — the roles, the politeness settings, that
an announcement fires and focus does not move, that the assertive channel
stays quiet on success — and axe-core checks the rule set. None of that is the
same as a VoiceOver or NVDA session, that session has not happened, and no
automated check here should be read as standing in for it.

Checked in two layers: `tests/test_ui.py` for markup, semantics, and computed
contrast, offline with no dependencies; and `tests/browser/` for the behaviors
only a browser can confirm, including axe-core's WCAG 2.2 AA rule set in
light, dark, and right-to-left.

```console
$ cd tests/browser && npm install && npm run check
49/49 behaviour checks passed
```

## Configuration

Everything tunable lives in [`cairn.toml`](cairn.toml), which ships with every
default written out: corpus and index locations, the relevance threshold
(bounded [0, 1]; calibrated against the demo corpus — re-check it against
probe questions when you swap corpora), how many passages compose an answer,
and the human-contact line refusals point to.

## Development

```console
$ python3 -m unittest discover -s tests   # zero third-party dependencies
$ ruff check .                            # lint (dev extra: pip install -e ".[dev]")
```

The test suite covers ingestion idempotency (byte-identical re-index), grounded
answering with citation validity and numeric-fact traceability, refusal
behavior (no sources, no corpus leakage, countable in JSON output), stage
diagnosis in explain mode, multilingual behavior including script-aware
tokenizing and bidi isolation, output determinism, and the CLI contract — and
it re-measures the retrieval threshold calibration on every run rather than
trusting a comment. It also runs every command in
[the walkthrough](docs/demo.md) and fails if the recorded output has drifted.

The browser checks under `tests/browser/` need Node and Chromium and are
deliberately not part of this path: install, lint and test work with no Node,
no browser, and no network.

## The merge gate

Cairn does not grade itself. `cairn record` asks the real engine a committed
set of questions and writes what came back as an evidence bundle; the merge
gate hands that bundle to [Plumbline](https://github.com/ChelseaKR/plumbline),
a separate project, pinned to an exact commit in
[`plumbline.pin`](plumbline.pin).

```console
$ python3 -m cairn record       # evidence, produced by the engine, not by hand
$ ./plumbline-gate.sh           # the same command CI runs
GATE: PASS — target cairn-demo, dataset 3222a8849261, run 958f5afdafd68ccb
all 14 suites passed:
  ...
  passage_attribution    score 0.9375  floor 0.90  PASS  n=16  3 unverifiable
  ...
$ python3 audit_guard.py        # and the check the gate cannot make on itself
GUARD: PASS — cairn-demo, run 958f5afdafd68ccb, against baseline 123b2569cb8a46ba
declared gaps: none — every implemented suite is enabled.
suites that could not check everything they were handed:
  passage_attribution: scored 16 of 19 eligible (no_distractor 3); unverifiable
  items are excluded, never passed
no suite moved against the committed baseline.
```

**The gate is advisory today, and this is the sentence that says so.** The
`audit` job runs on every pull request and writes a verdict; nothing yet stops
a pull request being merged while that verdict is red, because whether a check
can block a merge is a repository setting on GitHub's side and no file can
grant itself that power. The exact ruleset needed is written out and committed
at [`.github/rulesets/main.json`](.github/rulesets/main.json), deliberately not
applied, with what it costs and how to apply it in
[its README](.github/rulesets/README.md). Until someone with admin rights
applies it, a green tick here means the checks ran, not that they had to pass.
A check that could have blocked a merge and did not is the failure this whole
project is about; it would be a poor joke to hide one in it.

The harness is resolved at run time and verified to be at the pinned commit.
It is in no import and no dependency list, so Cairn's install, lint and test
path works with it completely unreachable — and CI proves that on every run,
in the same job that proves the gate **fails** in that condition. A skipped
check and a passed check are the same green tick on a pull request, so an
unresolvable auditor has to be red: a gate that could not run is not a gate
that passed.

Running it for real found four things worth fixing, including two languages
disagreeing about the same policy number and a Spanish refusal a standard
detector read as an answer. They are written up in
[DESIGN.md](DESIGN.md#what-the-first-audit-found), along with the two known
limits that are named rather than tuned away.

**A floor is a minimum, not a ratchet.** `accuracy` could fall from 0.3982 to
0.36 above a floor of 0.35 and the gate would be green the whole way down, so
the pin also names a committed baseline — one line per suite, distilled by the
harness from a run we were happy with — and `audit_guard.py` runs straight
after the gate and fails on any suite whose score no longer matches it, any
floor that was lowered, and any suite that stopped being scored. It can be
silenced by regenerating the baseline, which is the point: a move then arrives
as `"score": 0.9615` becoming `"score": 0.36` in a reviewed diff, rather than
as nothing at all.

**A score that went *up* fails too, and the guard still will not adopt it.**
An improvement nobody records is a bar nobody raised: the committed number
stays low, and every point of the improvement can be given back later with the
comparison calling it unchanged. So a rise stops the build exactly as a fall
does — labelled `IMPROVEMENT` rather than `REGRESSION`, because they do not
mean the same thing — and a person decides, in a commit, whether the better
number becomes the new bar. Nothing here ratchets by itself in either
direction, and a test pins that the guard never writes to the baseline.

**A suite that was not scored, and now is.** `multilingual` checks that a
response came back in the language it was asked in. It sat disabled because
the harness pinned at the time recognised English and Spanish only, while a
third of Cairn's evidence is Arabic — and it called an unrecognised language a
configuration error rather than scoring evidence it could not read, which is
right. Dropping the Arabic to make the suite runnable would have hidden the
language the interface exists to prove it supports. Cairn consumes Plumbline
at a pin and pushes nothing to it, so all Cairn could do was refuse to let the
gap read as coverage: declared in `plumbline/target.toml`, printed by the
guard beside every gate result, held there by a test, and written out with the
exact fix. Plumbline has since shipped Arabic recognition by script; bumping
the pin and enabling the suite scored it 1.0000 across all 26 items. The story
is kept in [DESIGN.md](DESIGN.md#the-gap-in-the-audit-closed-upstream-and-what-closing-it-took),
because a consumer finding a real gap in its own auditor and saying so until
it got fixed is the interlock working.

**And a second gap, the same way.** One item, `ck-022`, is answered from the
housing document's *deadline* paragraph instead of the one with the amount in
it — and thirteen suites passed it, each of them correctly. The answer is
grounded, in a real passage; the citation resolves; the cited passage supports
the answer completely, because that is where the answer came from. Nothing
could say **right document, wrong paragraph**. Cairn wrote the case up, named
what a suite would need, and Plumbline built `passage_attribution`. The
evidence side of it is authored: `plumbline/questions.toml` now declares which
passage answers each question, because only a person who has read the question
and the corpus can say that, and `cairn record` refuses a question set where
an answer item does not. The suite scores 0.9375 over 16 items and fails
`ck-022` by name — and is more precise than the write-up was, reporting it as
a *retrieval* failure, because the right passage never cleared the threshold
for composition to choose it. The behaviour has not changed; it is scored now
instead of only documented.

## Grading the server, not a recording of it

Everything above grades a bundle. A bundle is bytes on disk; the thing it is a
recording of is code that changes. So the same questions also get asked over
HTTP, against a running `cairn serve`, by the pinned harness's own live-target
recorder:

```console
$ ./plumbline-gate.sh           # resolves the harness; the only thing that does
$ ./plumbline-live.sh
PLUMBLINE LIVE: serving cairn on 127.0.0.1:8766
recorded:  26 responses
verdict: PASS
LIVE: MATCH — http://127.0.0.1:8766/ask, recorded 2026-08-16T…
  26 answers over HTTP, byte-identical to the recorded evidence the gate grades.
  the audited interface snapshot is the page being served.
```

**Wiring it up found something on the first run.** Pointed at the served
answer text, `citation_validity` scored 0.0000 — on a system the offline audit
scores 1.0000. The inline citation markers existed only inside `cairn record`:
`/ask` returned the sources as structured metadata and the answer text with
none in it, so the audit's perfect citation score described a string no
consumer of the served interface could get, and any plain-text client got an
answer with no sources. `Answer.cited_text` is one definition of that shape
now, used by the recorder and returned by the API. The bundle came out
byte-identical; only who can produce it changed.

**This is an addition, not the gate.** The merge gate stays `audit`: offline,
deterministic, grading committed bytes, with no socket anywhere in it.
`plumbline.pin` does not name the live config, `./plumbline-live.sh`
deliberately cannot resolve the harness — it uses the checkout the gate
verified, so grading a running server is never the act that installs its own
auditor — and the drift check itself runs in the core test suite against a
loopback server with no harness and no network at all.

## License

Apache-2.0 — see [LICENSE](LICENSE).
