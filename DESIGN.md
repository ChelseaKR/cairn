# Cairn — design document

Cairn is a reference implementation of a retrieval-grounded question-answering
assistant for public agencies. It answers only from a corpus the operator supplies,
cites its sources, and refuses cleanly when it has none.

This project is built from a functional specification (idea-level only; no code was
provided or consulted). All names, wording, file layouts, formats, and constants in
this repository are choices made here, and this document records the ones that
matter and why.

Build started: 2026-08-15.

## Why "Cairn"

A cairn is a stack of stones marking a verified trail. It guides you only where
someone has actually placed stones; where there are none, there is no trail and the
honest move is to stop. That is this system's contract: **grounded or silent**.

## Core stance

Three constraints from the specification shape every design decision below:

1. **Offline and deterministic by default.** The full demo path (install, index,
   ask, serve) runs with no network, no API key, no external model. Identical
   corpus + configuration + question ⇒ identical output, byte for byte.
2. **Config-driven.** Swapping the corpus or tuning behavior is a configuration
   change, never a code change.
3. **Grounded or silent.** There is no code path that emits an answer without
   supporting corpus passages.

## Architecture

Pure-Python, standard library only at runtime. This is not minimalism for its own
sake: "install offline on a laptop" is a hard requirement, and a zero-dependency
package means the demo path works from a clean checkout with nothing but a Python
interpreter — `python3 -m cairn ...` runs with no install step at all.

```
cairn/                  the package
  corpus.py             load + chunk corpus documents (front-matter markdown)
  index.py              build/read the on-disk index; deterministic serialization
  retrieve.py           TF-IDF cosine scoring, threshold gate, retrieval trace
  answer.py             grounded answer composition and refusal (the only two outcomes)
  config.py             TOML config loading with defaults
  cli.py                subcommands: index, ask, serve
  __main__.py           `python3 -m cairn` entry point
corpus/demo/            bundled synthetic demo corpus (clearly labeled synthetic)
tests/                  stdlib unittest suite (runs with zero third-party deps)
```

### Data flow

```
corpus dir ──corpus.py──▶ passages ──index.py──▶ .cairn/index.json
question  ──retrieve.py──▶ scored candidates ──threshold──▶ accepted passages
accepted passages ──answer.py──▶ grounded answer + sources   (≥1 accepted)
                                 refusal, no sources         (0 accepted)
```

### Answer composition is extractive

The default answering mode composes the answer **verbatim from the accepted
passages** (top-ranked passages, joined). No paraphrase, no synthesis, no template
that interleaves generated prose with facts. Consequences, all intentional:

- **Numeric traceability is structural, not audited-after-the-fact.** Every number
  in an answer appears character-for-character in a cited passage, because the
  answer *is* the cited passages. The spec's requirement that numeric policy facts
  be traceable to a cited passage is satisfied by construction.
- **Determinism is trivial.** No sampling, no model, no floating-point generation.
- An optional generative mode (external LLM rewriting accepted passages) is a
  possible later addition; the spec requires it be clearly separated and off by
  default, and the extractive path remains the reference behavior.

### Retrieval: TF-IDF cosine, not BM25

Scoring is cosine similarity between TF-IDF vectors of the query and each passage.
Chosen over BM25 because the score is **bounded [0, 1]**, which makes the relevance
threshold a legible, corpus-independent knob an operator can reason about. BM25's
unbounded scores would make the configured threshold meaningless across corpora.
Trade-off accepted: BM25 ranks marginally better on long documents; this corpus
model (short plain-language passages) does not exercise that advantage.

- Tokenization: Unicode word characters (`\w+`), lowercased via `str.casefold()`,
  then **truncation-stemmed to 5 characters** — a crude, dictionary-free,
  deterministic normalizer that unifies inflectional variants (month/monthly,
  deadline/deadlines, recibe/reciben) across suffixing languages with no
  per-language rules. Added after measured misses caused by exactly those
  variants; revisit in M3 when Arabic (non-suffixing morphology) joins.
- IDF: smoothed, `log((N + 1) / (df + 1)) + 1`; terms appearing in more than
  half the passages are ignored outright (df-based stopword suppression, no
  per-language stopword lists). TF is sublinear (`1 + log tf`). Both added after
  measured misses where repeated function words outweighed topical terms.
- Ties broken by passage id (lexicographic) so ranking is fully deterministic.
- **Tried and rejected:** pivoted length normalization (blending passage norms
  toward the corpus average, b ∈ {0.5, 0.6, 0.75}). Measured on the demo corpus
  it did not fix the one known hard case and degraded two Spanish rankings, so
  the simpler, more legible scorer stays.
- **Known hard case, kept on purpose:** the transit document cross-references
  the grocery program by name, and its short cross-referencing passage can
  outrank the grocery document's own eligibility passage for one phrasing of an
  income-limit question. Real corpora cross-reference constantly; this is the
  failure mode explain mode (R5, M2) exists to make visible, not something to
  tune away against a five-document corpus.

### Chunking

Documents are split into passages on blank-line paragraph boundaries. A
heading-only block is merged into the passage that follows it (a heading is
context, not content — it should never be a retrievable unit on its own, and its
words should count toward the passage they title). Passage ids are
`<doc-id>#<ordinal>` — stable as long as the document content is stable, and an
operator can look one up by opening the document and counting blocks.

### Corpus document format

Markdown files with a minimal front-matter block (`---`-delimited `key: value`
lines; parsed by Cairn itself, no YAML dependency):

```
---
id: grocery-allowance-en
title: Fresh Start Grocery Allowance
lang: en
synthetic: true
---
```

`id`, `title`, `lang` are required. `synthetic: true` is required for the bundled
demo corpus and surfaced in ingestion output, so the fictional content is labeled
at the data layer, not only in prose.

### The index

`cairn index` writes a single JSON file (default `.cairn/index.json`): passage
records (id, doc id, title, lang, text), per-passage term counts, document
frequencies, and passage count. Serialized with sorted keys and a fixed layout, so
**re-indexing an unchanged corpus is byte-identical** — idempotency is testable
with a file hash, not argued in prose. The CLI reports the count of passages and
documents indexed and the path written.

Scores are computed at query time from stored term counts. For corpora that fit a
laptop demo this is milliseconds; precomputed vectors are an optimization the
reference implementation does not need.

### Refusal is a first-class outcome

`answer.py` returns exactly one of two result kinds: `grounded` or `refusal`.
A refusal:

- states plainly that the assistant has no source for the question and cannot
  answer it;
- points to a human channel, taken from configuration (`[refusal] contact`) —
  wording lives in one place and an agency changes it without touching code;
- carries **no** sources list and no partial or hedged guess;
- exits with status 0 and is countable (the `kind` field in `--json` output).
  Non-zero exit codes are reserved for real errors (missing index, bad config).

## Configuration

TOML (`cairn.toml` at the repo/deployment root; `--config` overrides), read with
stdlib `tomllib`. All keys have defaults; the file may be sparse.

| Key | Default | Why this value |
| --- | --- | --- |
| `corpus.path` | `corpus/demo` | the bundled synthetic corpus, so a clean checkout works immediately |
| `index.path` | `.cairn/index.json` | dot-directory keeps generated state out of the operator's way |
| `retrieval.threshold` | `0.20` (measured) | bounded-cosine gate, set empirically against the demo corpus — see the measurement note below |
| `retrieval.max_passages` | `2` | enough to answer multi-part questions; more starts pasting unrelated passages |
| `retrieval.candidates` | `8` | candidates scored/reported (matters for explain mode); retrieval quality does not depend on it |
| `refusal.contact` | demo office string | fictional demo contact; a real agency must set this |

> **Measured 2026-08-15** (8 in-corpus probes in English and Spanish, 6
> off-topic probes, final scorer): top scores for in-corpus questions fall in
> **0.239–0.453**; off-topic questions top out at **0.169**. The provisional
> default of 0.28 would have wrongly refused a legitimate question scoring
> 0.239, so the default is **0.20** — inside the measured gap, with margin on
> both sides. The probe set lives in the test suite, so the calibration is
> re-checked on every run, not just asserted here.

## Language and interface decisions

- Python ≥ 3.11 (for `tomllib`). Developed on 3.12.
- CLI subcommands: `cairn index`, `cairn ask "…"`, `cairn serve`. `--json` on
  `ask` emits a machine-readable record (also the substrate the auditor interlock
  will consume later). `--explain` and `--lang` exist as flags now but are honest
  stubs that name their milestone and exit 2 rather than half-working.
- Tests are stdlib `unittest` so the core dev path (`python3 -m unittest`) needs
  no third-party install at all. They are pytest-compatible for anyone who
  prefers that runner. Lint is `ruff` when available (declared as a dev extra),
  never required by the demo path.

## Roadmap

Milestones map to the specification's functional requirements. M1 is this build's
scope; later milestones have skeletons (stub commands/flags, data already carried
in the index) but no rushed half-implementations.

| Milestone | Spec requirement | Scope |
| --- | --- | --- |
| **M1 (now)** | R1 ingestion/indexing | CLI `index`, idempotent, reports counts + path |
| **M1 (now)** | R2 grounded answering | extractive answers, threshold gate, sources list with titles + stable ids, numeric traceability by construction |
| **M1 (now)** | R3 refusal | first-class refusal outcome, configured human channel, no sources, no guess; tested and countable |
| **M1 (now)** | (groundwork) | synthetic demo corpus in English and Spanish; config; unittest suite; docs for the offline demo path |
| **M2** | R5 explain mode | `ask --explain`: every candidate with score, accepted/rejected at threshold, explicit grounded/not-grounded verdict. The retrieval trace data structure already exists in M1 (`retrieve.py` returns it); M2 is the renderer and its tests |
| **M3** | R4 multilingual | third language (Arabic, RTL) in demo corpus; language selection; same-language source preference (passage `lang` is already indexed in M1); answer-language matching |
| **M4** | R6 + R7 UI/docs | accessible chat UI (WCAG 2.2 AA behaviors: skip link, polite live-region transcript, interrupting error channel, labeled input, standing AI disclosure, light/dark), served by stdlib `http.server`; demo walkthrough doc with a CI check that docs and actual output do not drift |
| **M5** | auditor interlock | auditor pinned by exact commit in `auditor.pin` (single file read by local tooling and CI), resolved at run time — never a package dependency; gate job fails (never skips) when the auditor is unreachable, with the reason written into the workflow as a comment. Core install/lint/test stays fully independent of the auditor |

Ordering rationale: explain mode (M2) before multilingual (M3) because it is the
operator's debugging instrument — it makes every later milestone cheaper to verify.
UI last among the feature milestones because it renders behaviors the engine must
already have. The interlock closes the loop once there are recorded answers worth
auditing.

## Decisions where the specification was silent

- **What "answer composition" means offline:** resolved as extractive (see above).
  The spec forbids an external model in the default path and requires determinism;
  extraction is the honest way to have both.
- **Score normalization:** bounded cosine chosen specifically so the configurable
  threshold is meaningful (see Retrieval).
- **Refusal exit code:** 0. The spec says refusal is not an error state; the exit
  code says so too.
- **Passage identity scheme:** `doc-id#ordinal` rather than content hashes —
  human-legible and stable under re-indexing, at the cost of shifting if a
  document's paragraph structure is edited. For a corpus of published policy
  documents, edits produce a new document version anyway.
- **Demo corpus fiction:** an invented agency ("Harbor County Community
  Assistance") with invented programs and invented numbers, `synthetic: true` in
  every file's front matter, and a corpus README stating it. Phone numbers use
  the 555 range.
- **Two demo languages in M1:** the corpus-side requirement (synthetic content in
  at least two languages) lands now (English + Spanish); the behavioral
  multilingual requirement (R4) is M3. Arabic joins the corpus in M3 with RTL.
