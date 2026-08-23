# The real-corpus pilot: working directory

The design, the findings so far, and the pre-registered decision gate are in
[`docs/pilot-ca.md`](../../docs/pilot-ca.md). This file is the workflow.

## Layout

```text
corpus/pilot-ca/
  pilot.toml              layers and counties, with each county's refusal contact
  cairn.template.toml     rendered into every assembled corpus's cairn.toml
  sources/<layer>.toml    URL lists, one per layer, each with its terms and
                          the date a person read them; two are `blocked`
                          (see Finding 0)
  layers/<layer>/*.md     the corpus, one directory per layer — reviewed
                          front-matter markdown, and tables/*.csv under it
  candidates.toml         564 unlabelled candidate questions from public
                          sources (collect_queries.py); not evidence
  questions.toml          the labelled question set (not yet written)
  probes.toml             derived from questions.toml by probes_from_questions.py
  assembled/              derived, .gitignored: one corpus directory per county
source_pages/<layer>/     derived, .gitignored: fetched HTML and manifest.json
```

## Workflow, one layer at a time

```text
$ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal
```

Pages whose sites refuse scripts (the list says which) are saved from a
real browser. `browser_save.mjs` drives Chromium through the Playwright
that `tests/browser/` pins (`cd tests/browser && npm ci && npx playwright
install chromium`, once):

```text
$ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal --browser-jobs
$ node browser_save.mjs source_pages/federal            # --headless works for most sites
$ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal --hand-saved
```

A page a person saves by hand goes in the same directory under the same
`file` name and is registered by the same last step; the manifest records
`saved_by` only for the browser script's saves, so it always says which.

Then scaffold — provenance comes from the manifest, never typed:

```text
$ python3 import_corpus.py --batch source_pages/federal -o corpus/pilot-ca/layers/federal
```

**Then review.** Every scaffold carries `review: unreviewed` and an id
prefixed `review-`, and `assemble_corpus.py` refuses to include it until
both are gone. Reviewing a page means: read it against the source; fix the
id to something stable (`ssa-retirement-en`, not `review-retirement`);
delete anything that is not the page's own content; decide whether a table
stays as prose or moves to `tables/<id>.csv`; add `reviewed_at:
YYYY-MM-DD`; delete the `review:` line. A page that turns out to be a form,
a tool, or a landing page of links comes off the source list instead.

Committing unreviewed scaffolds is fine and expected — the review is then a
reviewed diff per file, which is the right shape for it — because the
assembly step, not the commit, is where an unreviewed document would become
a corpus document, and that step refuses.

Assemble, index, lint:

```text
$ python3 assemble_corpus.py corpus/pilot-ca --county sonoma -o corpus/pilot-ca/assembled/sonoma
$ python3 -m cairn --config corpus/pilot-ca/assembled/sonoma/cairn.toml index
$ python3 -m cairn --config corpus/pilot-ca/assembled/sonoma/cairn.toml lint
```

`--allow-unreviewed` exists for smoke runs of the pipeline and says so in
its output. Nothing produced under it is a measurement.

## Questions

```text
$ python3 collect_queries.py --msmarco source_pages/msmarco --download --stackexchange -o corpus/pilot-ca/candidates.toml
```

draws candidates from MS MARCO (real search queries; non-commercial
research) and Stack Exchange (CC BY-SA, attributed). They are not
questions until a person reads the corpus and labels them into
`questions.toml` — `docs/pilot-ca.md`, "The question set", has the fields.

## Measuring

Once `questions.toml` exists and is labelled:

```text
$ python3 probes_from_questions.py corpus/pilot-ca/questions.toml -o corpus/pilot-ca/probes.toml
$ python3 -m cairn --config corpus/pilot-ca/assembled/sonoma/cairn.toml calibrate --probes corpus/pilot-ca/probes.toml
$ python3 -m cairn --config corpus/pilot-ca/assembled/sonoma/cairn.toml record --questions corpus/pilot-ca/questions.toml --out pilot-ca-bundle
$ python3 sweep.py --config corpus/pilot-ca/assembled/sonoma/cairn.toml --questions corpus/pilot-ca/questions.toml --at 0.165 --json curve.json
```

`sweep.py` reads the labels the recorder ignores (`source`, `jurisdiction`,
`county`, `location_dependent`) and splits the rates by each; with the
assembled corpus's `layers.json` it also labels wrong answers as
`jurisdiction-mismatch` or `wrong-county` mechanically. Every label it
prints is a first pass for a person to check.

## The county layers

The pilot's counties are San Mateo, Sonoma and Siskiyou, chosen by their
terms after a survey of all 58 (`docs/pilot-ca.md`, Finding 0). Siskiyou's
host refuses scripts, so its pages are hand-saved. `sources/los-angeles.toml`
and `sources/fresno.toml` are `blocked`, with the terms quoted in the file,
and are kept as the record of why those counties are not here;
`fetch_pages.py` refuses a blocked list, and what would unblock one is
written permission on file, not an edit.
