# Cairn

Retrieval-grounded question answering for public agencies, as a reference
implementation: it answers **only** from a corpus the operator supplies, shows
its sources on every answer, and when no source clears the relevance threshold
it refuses plainly and points to a human — no guessing, ever. A cairn marks a
verified trail; where there are no stones, there is no trail.

**Status: pre-release.** Ingest, grounded answers with citations, refusal, and
the operator explain mode are complete; multilingual operation, the accessible
chat UI, and the CI audit interlock are on the
[roadmap](DESIGN.md#roadmap). This is a demonstration of correct behavior, not
a production service.

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
Indexed 20 passages from 5 documents (5 marked synthetic) -> .cairn/index.json

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

## The demo corpus is synthetic

The bundled corpus under [`corpus/demo/`](corpus/demo/) is **entirely
fictional**: an invented agency, invented programs, invented amounts and
deadlines, in English and Spanish, each file marked `synthetic: true`. See
[its README](corpus/demo/README.md). Point `[corpus] path` in
[`cairn.toml`](cairn.toml) at your own directory of front-matter markdown
documents to use real content — swapping the corpus is a config change, never
a code change.

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
behavior (no sources, no corpus leakage, countable in JSON output), output
determinism, and the CLI contract — and it re-checks the retrieval threshold
calibration on every run.

## License

Apache-2.0 — see [LICENSE](LICENSE).
