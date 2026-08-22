# Finding corpus gaps from refusals, without keeping the questions

A refusal already says something useful: the corpus didn't cover this. Over
enough real traffic, the *pattern* of refusals — which language, which
reason — points staff at exactly the gaps worth closing next. Getting that
signal has always meant keeping the questions themselves, which this project
does not do: `cairn serve`'s module docstring says it logs nothing about the
questions people ask, and that has been true since before this feature
existed.

`--refusal-stats` is the answer to "can we have the signal without the
questions" — strictly opt-in, and structurally unable to carry a question
even if an operator wanted it to.

## Turning it on

```console
$ cairn serve --refusal-stats refusal-stats.json
```

Every refusal increments one counter, keyed by the language it was asked in
and a fixed reason code — not the question, not the client, not a
timestamp. Nothing else about `cairn serve` changes: a grounded answer is
never counted, and with the flag unset the file is never created and
nothing about a refusal is any different from before this existed.

## Reading the file

```console
$ cairn refusals refusal-stats.json
3 refusal(s) recorded, by language and reason:

  es   no-passages-in-language  1
  en   no-lexical-overlap       1
  en   below-threshold          1

Reason codes:
  no-passages-in-language  the corpus holds nothing at all in this language — a coverage gap, not a ranking problem.
  no-lexical-overlap       no passage shared even one scoring term with the question — likely a vocabulary gap between how the corpus and the question say the same thing, not a ranking one.
  below-threshold          candidates were scored but none cleared the configured threshold — a near-miss; see `cairn calibrate`.
```

The three reason codes are the same ones `cairn ask --explain` already names
for the retrieval stage (see DESIGN.md, "Explain mode reports stages, not
just scores") — this is that same diagnosis, aggregated across every
refusal instead of run by hand against one question at a time:

- **`no-passages-in-language`** is the starkest gap: staff asked in a
  language the corpus has nothing in at all. If Spanish shows up here
  repeatedly, the corpus needs Spanish content, not a retrieval tweak.
- **`no-lexical-overlap`** usually means the corpus covers the topic but
  says it differently than people ask it — a vocabulary gap. `docs/authoring.md`'s
  FAQ-pair convention (writing a passage in the phrasing people actually
  use, not just the policy's own phrasing) is the direct fix.
- **`below-threshold`** is a near-miss: something scored, but not enough.
  Worth checking with `cairn calibrate` against real probe questions before
  assuming the corpus itself is missing anything — sometimes the threshold
  is simply set a little too high for this corpus.

The underlying JSON file (`refusal-stats.json` above) is a plain object —
`{"en": {"below-threshold": 1, ...}, ...}` — an operator can also read
directly, feed into their own reporting, or version-control snapshots of
over time to watch a gap close.

## What this is not

- **Not a query log.** There is no way, from this file, to recover what
  anyone asked, when, or from where. A count of `3` under `es` /
  `no-lexical-overlap` is the same file whether it came from three different
  people or one person trying three times — that indistinguishability is
  the design, not a limitation to work around.
- **Not real-time.** The file is a snapshot as of the last refusal; `cairn
  refusals` re-reads it each time it's run. There's no dashboard, no
  streaming, no alerting — an operator (or a cron job piping the file
  somewhere) decides how often to look.
- **Not a substitute for `cairn lint`, `cairn calibrate`, or `cairn diff`.**
  Those tell an operator about the corpus as it exists on disk. This tells
  them about the corpus as real questions have actually exercised it — a
  different signal, and one that only exists once there is real traffic to
  learn from.
