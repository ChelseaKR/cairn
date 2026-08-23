# The real-corpus pilot: six pages from usa.gov

Everything else this project measures itself against — the bundled demo
corpus, `plumbline/questions.toml`, the calibration probe example — is
synthetic, authored for this repository, by someone who already knew what
Cairn needed a corpus to look like. This page is the one measurement against
content nobody wrote for Cairn: six real, currently-published pages from
[usa.gov](https://www.usa.gov), the U.S. federal government's official
public-services site, imported with this repository's own tooling and
answered with no authoring help beyond what a competent transcription
requires.

**What this is not**: a claim that these six pages are a complete or
representative sample of everything a real deployment would face, or that
usa.gov's content is typical of every agency's writing style. It is one
honest data point, gathered the way the pipeline is supposed to be used, and
reported the way this project reports everything else — including the parts
that did not work on the first pass.

## What was imported

Six pages, fetched on 2026-08-23 and transcribed faithfully — not rewritten,
not condensed, no sentence added that the source page did not already
contain:

| Document | Program | Language | Source |
|---|---|---|---|
| `snap-en` | SNAP (food stamps) | English | usa.gov/food-stamps |
| `energy-bills-en` | LIHEAP + WAP (energy bills) | English | usa.gov/help-with-energy-bills |
| `lifeline-en` | Lifeline (phone/internet) | English | usa.gov/help-with-phone-internet-bills |
| `section8-en` | Section 8 housing vouchers | English | usa.gov/housing-voucher-section-8 |
| `wic-en` | WIC | English | usa.gov/food-assistance |
| `snap-es` | SNAP (food stamps) | Spanish | usa.gov/es/solicitar-cupones-alimentos-snap |

Each file's front matter carries `source:` (the exact URL) and
`reviewed_at:` — inert to Cairn, both purely for a reader's own use, the
same convention `docs/onboarding.md` already documents for `reviewed_at`.
`synthetic: false` on every one, correctly, since every fact in these files
is a real federal program's own published description, not invented for a
demo.

**One real, immediate finding about the source material itself:** these are
federal overview pages, and overview pages defer specifics to state-level
offices. Not one of the six pages states a dollar amount, an income
threshold, or a specific deadline — everything the bundled demo corpus
bakes in for testability (`$212 per month`, `$2,430`) usa.gov instead says
"contact your state or local office" or "eligibility is based on your
income" with no number attached. A real deployment built from *only*
federal umbrella pages like these would ground plenty of "what is this
program" and "how do I apply" questions and refuse every dollar-amount
question outright, correctly — there is no dollar amount to cite. This is
not a defect in Cairn; it is the corpus telling the truth about what it
does and does not know, exactly as designed. It does mean a real deployment
answering "how much" questions needs its state or local office's own pages
in the corpus too, not just the federal umbrella page.

## The pipeline, run as documented

```console
$ python3 import_corpus.py --batch source_pages/ -o corpus/pilot-usagov/
Batch: 6/6 file(s) scaffolded, 56 paragraph(s) total.
REVIEW REQUIRED for every file above before any of them is a real corpus document.
```

Every file still needed the mandatory review step `docs/onboarding.md`
describes — not a formality here. The first review pass found a real defect
(below); the corpus committed to `corpus/pilot-usagov/` is the *second*,
corrected pass.

```console
$ cairn --config corpus/pilot-usagov/cairn.toml lint
Linted 6 document(s) in corpus/pilot-usagov
No issues found.

$ cairn --config corpus/pilot-usagov/cairn.toml calibrate --probes corpus/pilot-usagov/probes.toml
16 probe(s) against threshold 0.165
  [... 16 lines, all "ok" ...]
Worst 'answer' probe score:  0.239
Best 'refuse' probe score:   0.111
Gap: 0.129  Suggested threshold (midpoint): 0.175
Configured threshold 0.165 classifies every probe correctly.

$ cairn --config corpus/pilot-usagov/cairn.toml record \
    --questions corpus/pilot-usagov/questions.toml --out /tmp/pilot-bundle
Recorded 16 items (10 answers, 6 refusals) in 2 languages [en, es] -> /tmp/pilot-bundle
```

The recorded bundle itself is not committed — it is a derived artifact, the
same reason `.cairn/index.json` is gitignored, and it is not part of the
audited evidence path (`plumbline/bundle/`, graded by the pinned external
harness). `corpus/pilot-usagov/probes.toml` and `questions.toml` are
committed, so anyone can reproduce every number on this page by running the
three commands above.

## Finding 1: transcribing a page's own heading into the body doubles it as a passage, and it wins

The first review pass scaffolded each page with its own `<title>`/H1 text
as the body's first line — the literal, faithful thing to do when
transcribing a page that visibly shows that heading. Every one of the six
documents' *first* passage was therefore the page's own title, repeated.

Asking the resulting corpus **"How do I check my SNAP EBT balance?"**
retrieved the *title* passage (`snap-en#1`, "How to apply for food stamps
(SNAP benefits) and check your balance") — not the passage that actually
answers the question (`snap-en#4`, "Every state issues SNAP benefits on an
EBT card. To check how much money is left on your EBT card…"), even though
the balance passage matched **5 of 5** question terms against the title
passage's 4 of 5:

```
   1  0.597  ACCEPT  snap-en#1  matched 4/5: balan, check, how, snap
   2  0.555  ACCEPT  snap-en#4  matched 5/5: balan, check, ebt, how, snap
```

The title passage still scored higher. It is short — one sentence — and
TF-IDF cosine's length normalization rewards a passage where every word
that matches is a larger fraction of the whole passage. A page's own title,
restated as body text, is exactly the shape that wins this way: short,
generic, and lexically present in almost every question about that page's
topic.

**Fix:** delete the duplicated title line from the body. Nothing else
changes — the title still exists as the front-matter `title:` field and is
already weighted into every passage's score at index time (`cairn lint`'s
own description of the title's role); duplicating it into the body a second
time was pure redundancy that happened to win by default. After the fix,
the same question correctly retrieves `snap-en#4`:

```
$ cairn ask "How do I check my SNAP EBT balance?"
## Check your SNAP balance
Every state issues SNAP benefits on an EBT card. To check how much money is
left on your EBT card: ...
Sources:
  [1] How to apply for food stamps (SNAP benefits) and check your balance (snap-en#4)
```

**This is now added to `docs/onboarding.md`'s import guidance** — the
single highest-value correction this pilot found, because it is entirely
mechanical (no judgment call, no per-corpus tuning) and would silently
degrade every real corpus imported the naive way.

## Finding 2: short overview passages can still outrank a longer, more specific one — and `max_passages` compounds it

Even after fixing Finding 1, the same length-normalization effect showed up
between a document's own short *introduction* paragraph and its longer,
more specific answering paragraphs. Asking **"Am I eligible for Section 8
housing?"**:

```
   1  0.806  ACCEPT  section8-en#1  (the one-sentence introduction)
   2  0.727  ACCEPT  section8-en#4  (the actual eligibility criteria)
```

Both cleared the threshold with a healthy margin (0.079 apart, both well
above 0.165), and `section8-en#4` — income, family size, immigration
status — is unambiguously the better answer to an eligibility question. But
the *default* `retrieval.max_passages = 1` means only the single top-scored
passage is composed into the answer, so the introduction wins by a nose and
the specific criteria are dropped. The same pattern reproduced for "What is
LIHEAP?" (the application-steps passage narrowly outscored the definition
passage).

**This is not a corpus defect** — both passages are correct, cited,
grounded content — **it is a real interaction between passage-length
variance and `max_passages=1`** that a synthetic corpus authored with
uniform, dense passages (the bundled demo corpus) never exercises. Raising
`retrieval.max_passages` to `2` in a scratch config fixed both cases
immediately, composing the introduction *and* the specific answer together:

```
$ cairn ask "Am I eligible for Section 8 housing?"   # max_passages = 2
A Section 8 housing choice voucher can help you pay rent for private housing...

## Find out if you are eligible for Section 8 housing
Eligibility for Section 8 housing is based on your total annual gross
income, your family's size, and if you are a U.S. citizen or non-citizen
with eligible immigration status.
```

**Recommendation:** a real corpus built from pages with a short
introduction followed by longer specific sections — a common real-world
document shape this pilot's synthetic sibling does not have — should
consider `retrieval.max_passages = 2` (or measure with `cairn calibrate`
and `ask --explain` on its own real probe set, the same way this page did)
rather than trusting the default that works fine on the demo corpus's more
uniform passages.

## Finding 3: a genuine vocabulary gap did surface, once

**"Who qualifies for WIC?"** scored its accepted passage at **0.239** — the
lowest of the ten answer probes, and the true eligibility passage
("...you must be at least one of the following: pregnant, breastfeeding
...") scored **0.164**, one thousandth below the 0.165 threshold, and was
rejected outright:

```
   1  0.239  ACCEPT  wic-en#4   matched 1/3: wic          (a different, more general passage)
   6  0.164  reject  wic-en#2   matched 1/3: wic          (the actual eligibility criteria)
```

Neither passage shares the word "qualify"/"qualifies" with the question at
all — the *only* term either has in common with "Who qualifies for WIC?"
is "wic" itself, present in the title-weighted score of every passage in
the document. This is the same failure DESIGN.md documents for the
synthetic corpus's own colloquial-recall case ("who can get the discount
bus pass"): real content, in its own real words, does not always contain
the words a real person asks with.

**This is the one finding that matches what a vocabulary-gap ceiling looks
like** — and it is one borderline case out of ten answer probes, still
correctly classified (the accepted passage, while not the most specific
one, is still truthfully about WIC eligibility support), not a dominant
failure mode. `docs/authoring.md`'s FAQ-pair convention — writing the
question a real person would ask directly into the passage that answers
it — is the documented, already-adopted fix for exactly this shape of gap,
and it was deliberately **not** applied to this pilot corpus, so this
finding would be visible rather than papered over before anyone measured
it. Applying it to `wic-en#2` (adding a sentence like "Who can get WIC?" is
answered by...") is the next, obvious step for this specific document, not
attempted here because doing so would then be measuring an edited corpus,
not the naive import this page is honestly reporting on.

## Calibration and refusal behavior

`cairn calibrate` against 16 probes (10 answer, 6 refuse; English and
Spanish) found the demo corpus's own `retrieval.threshold = 0.165` classified
every one correctly, with a suggested midpoint of 0.175 — ten thousandths
away. **This corpus did not need its own threshold.** That is worth stating
plainly since it could easily have gone the other way: six real pages from
an agency that never saw Cairn's threshold could have needed a
meaningfully different one, and did not.

All six off-topic refusal probes (passport renewal, a general-knowledge
question, voter registration, a tax question, unemployment insurance, and
one in Spanish) refused correctly, every one scoring well under 0.165. The
refusal message correctly fell back to Cairn's own built-in fictional
placeholder contact (`cairn/config.py`'s `_DEMO_CONTACTS`) since this pilot's
`cairn.toml` never configured a real one — the safety net named in
`docs/compliance.md` and `SECURITY.md` working exactly as intended on a
corpus that was never told to configure it, not a defect this pilot found.

## What this means for item #30 (semantic retrieval)

The expansion round this pilot belongs to named a contingent next step:
evaluate optional semantic retrieval, but only if this pilot's findings
showed the vocabulary-gap ceiling actually dominating refusals in real
content. **It did not.** Of the three findings above, the two with the
largest measured effect on answer quality — the duplicated-title passage
winning by default, and a short introduction outscoring a longer specific
passage under `max_passages=1` — are both **authoring and configuration
issues inside the existing lexical, extractive architecture**, fixed with a
one-line edit and a one-field config change respectively, not "found a
better answer that lexical matching cannot reach without semantic
embeddings." Finding 3, the one genuine vocabulary gap, was a single
borderline probe out of ten, already correctly answered (if not from the
most specific passage), and already has a documented, adopted fix
(`docs/authoring.md`'s FAQ-pair convention) that does not require
semantic retrieval, embeddings, or anything that would compromise the
offline-determinism and "every fact appears in a cited passage" invariants
DESIGN.md holds non-negotiable.

**Recommendation: do not pursue semantic retrieval.** This is consistent
with the repository's own measured history — DESIGN.md's account of
twenty-one ranking configurations built and reverted trying to solve a
vocabulary problem with a ranking change, when authoring the missing words
into the passage that needed them was the fix that actually worked, both
on the original synthetic case and, now, on real content. The two changes
this pilot actually recommends — stop duplicating a page's own title into
its body, and default real, unevenly-shaped corpora toward
`max_passages ≥ 2` — cost nothing in complexity, offline determinism, or
the citation guarantee, and address a larger share of what this pilot
measured than a semantic layer plausibly would.

## Reproducing this page's numbers

```console
$ cairn --config corpus/pilot-usagov/cairn.toml index
$ cairn --config corpus/pilot-usagov/cairn.toml lint
$ cairn --config corpus/pilot-usagov/cairn.toml calibrate --probes corpus/pilot-usagov/probes.toml
$ cairn --config corpus/pilot-usagov/cairn.toml ask --explain "Am I eligible for Section 8 housing?"
```

`tests/test_pilot_usagov.py` holds the corpus to the shape this page
describes — six documents, no lint errors, the probe set still calibrates
safely — so a future edit that quietly breaks one of these numbers fails a
test rather than making this page wrong silently.
