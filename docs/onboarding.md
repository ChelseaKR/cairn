# Onboarding a real corpus, and keeping it honest over time

This is guidance for getting an agency's actual documents into Cairn, and
for noticing when they have drifted from the source they were taken from.
Two separate concerns, covered together because they're the two halves of
"a corpus that started right stays right":

1. **Getting content in**: `import_corpus.py`
2. **Knowing when it's gone stale**: the `reviewed_at` convention and
   `cairn lint --max-age-days`

Neither changes what `cairn index` reads. Both are conventions and tooling
built entirely on the existing markdown-with-front-matter format (see
`cairn/corpus.py`) — an agency's real corpus is still just files in a
directory, reviewed by a person before they're real.

## Getting content in

`cairn index` reads exactly one format: markdown with a minimal front-matter
block. Real agencies have PDFs, Word exports, existing CMS pages — not
hand-authored markdown. `import_corpus.py` is a standalone, offline,
stdlib-only conversion script (never wired into `cairn index` or any runtime
path) that scaffolds a `.txt` or `.html` file into that format, with a
mandatory human-review step before the output is a real corpus document —
see the file's own docstring for the single-file case.

For more than one document at a time:

```console
$ python3 import_corpus.py --batch source_pages/ -o corpus/mine/
--- notice1.txt ---
Wrote corpus/mine/notice1.md (2 paragraph(s) extracted)
...
--- notice2.html ---
Wrote corpus/mine/notice2.md (1 paragraph(s) extracted)
...
Batch: 2/2 file(s) scaffolded, 3 paragraph(s) total.
REVIEW REQUIRED for every file above before any of them is a real corpus document.
```

`--batch` treats the input as a directory (non-recursive, the same flat
layout `cairn.corpus.corpus_paths` reads a real corpus from) and scaffolds
every `.txt`/`.html` file in it. `--id` and `--title` don't apply in batch
mode — each file's id and title are derived the same way the single-file
path derives them when neither is given, from the `<title>` tag or the
filename. A file that fails to extract (empty, unreadable) does not stop
the rest of the batch: the summary line says how many succeeded, and a
partial failure exits 1 so a script driving this notices.

**The review step is not optional, and batch mode does not skip it.** Every
scaffolded file still carries `review: unreviewed` in its front matter (an
extra key, inert to Cairn — see `cairn/corpus.py`'s module docstring) and a
doc id prefixed `review-` until a human renames it. A batch of ten files is
ten files someone has to actually read before they answer questions on an
agency's behalf, not once.

What this script explicitly does not do: read PDFs. Its two input formats
are plain text and HTML, on purpose — adding a PDF library would either
become a runtime dependency (breaking the zero-dependency claim this project
makes about the package it ships) or a dev-only one bolted onto a script
that is supposed to stay simple enough to read in one sitting. Converting a
PDF to text or HTML first, with whatever tool an operator already trusts for
that, is a deliberate seam, not a gap nobody noticed.

## Knowing when it's gone stale

The index carries a fingerprint of the corpus it was built from
(`cairn/index.py`), so Cairn always knows when a document has changed *since
the last `cairn index`*. It has no way to know when a document is wrong
*relative to the real world* — an agency's benefit amount changes, a
deadline passes, and the corpus file just sits there, byte-for-byte
unchanged, confidently quoted as current.

`reviewed_at` is an optional front-matter key — a date, in `YYYY-MM-DD`, an
author sets by hand the last time they actually checked a document against
its real source (the agency's live webpage, the actual policy document, a
conversation with the program office). Like `review`, it is inert to
everything that answers a question: retrieval, scoring, and citation never
read it.

```
---
id: grocery-allowance-en
title: Fresh Start Grocery Allowance
lang: en
synthetic: true
reviewed_at: 2026-08-01
---
```

`cairn lint --max-age-days N` is the one thing that reads it, and only when
an operator asks:

```console
$ cairn lint --max-age-days 90
  WARNING corpus/mine/grocery-allowance.en.md: last reviewed on 2026-01-15, 208 day(s) ago — over the 90-day staleness window. Confirm it still matches its real source and update 'reviewed_at'.
  WARNING corpus/mine/transit-pass.en.md: no 'reviewed_at' front-matter key: staleness cannot be tracked for this document. Add 'reviewed_at: YYYY-MM-DD' the next time it is checked against its real source.
```

Without `--max-age-days`, `cairn lint` never looks at `reviewed_at` at all —
a corpus that has never adopted the convention gets exactly as quiet a lint
as it always did. This is deliberate: staleness tracking is something an
operator opts into, not something sprung on a corpus that was never built
with it in mind.

**This is a reminder, not a guarantee.** A document with a recent
`reviewed_at` is only as current as the last person who checked it was
thorough — the date says a human looked, not that Cairn verified anything.
And it is entirely possible for content to go stale faster than any
staleness window catches it (an emergency policy change the day after
someone reviewed it). What this closes is the much more common failure: a
document nobody has looked at in a year, sitting in the corpus, answered
from with the same confidence as one reviewed yesterday, with nothing
anywhere saying which is which.
