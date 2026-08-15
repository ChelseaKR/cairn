# Cairn

Retrieval-grounded question answering for public agencies, as a reference
implementation: it answers **only** from a corpus the operator supplies, shows
its sources on every answer, and when no source clears the relevance threshold
it refuses plainly and points to a human — no guessing, ever. A cairn marks a
verified trail; where there are no stones, there is no trail.

**Status: pre-release.** Ingest, grounded answers with citations, refusal, the
operator explain mode, multilingual operation including right-to-left, and the
accessible chat interface are complete; the CI audit interlock is on the
[roadmap](DESIGN.md#roadmap). This is a demonstration of correct behavior, not
a production service.

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
Candidates (2 scored, ranked):
   1  0.067  reject  grocery-allowance-en#3  [en] Fresh Start Grocery Allowance
   ...
Stage 1 - retrieval: FAILED (below-threshold)
  2 candidates were scored and none cleared the 0.200 threshold. ...
Stage 2 - answer: NOT REACHED (no-evidence)
  The answer stage was handed no passages, so it refused. ...

Verdict: NOT GROUNDED - refusal, no sources.
Diagnose at: retrieval.
```

The point is the last line. A wrong answer whose retrieval stage passed is a
different bug from one whose retrieval stage failed, and the trace says which
you have — including the case where the right passage cleared the threshold and
was then dropped from the answer by `retrieval.max_passages`. Add `--json` for
the same trace machine-readably. Explain mode never changes the answer.

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

Checked in two layers: `tests/test_ui.py` for markup, semantics, and computed
contrast, offline with no dependencies; and `tests/browser/` for the behaviors
only a browser can confirm, including axe-core's WCAG 2.2 AA rule set in
light, dark, and right-to-left.

```console
$ cd tests/browser && npm install && npm run check
46/46 behaviour checks passed
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

## License

Apache-2.0 — see [LICENSE](LICENSE).
