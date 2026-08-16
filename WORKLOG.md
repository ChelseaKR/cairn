# Work log

One line per implementation session: date, what was built, from what input.

- 2026-08-15 — Session 1 (AI implementation session, clean-room implementation
  side). Input: the engine functional specification plus the clean-room
  protocol's hygiene rules; no other documents, repositories, or code. Built
  milestone M1: design document, package scaffold, corpus loader, synthetic
  en/es demo corpus, deterministic index, TF-IDF retrieval with measured
  threshold calibration, grounded/refusal answering, CLI, test suite, README.

- 2026-08-15 — Session 2 (AI implementation session, clean-room implementation
  side). Input: the same specification and hygiene rules, plus this
  repository's own state; and, for the final milestone only, the public
  Plumbline repository consumed exactly as any other user of it would — its
  README, its documented bundle format, and the gate runner its documentation
  tells consumers to copy. No other repository was read.

  Built M2 through M5: operator explain mode with a per-stage diagnosis;
  Arabic with real right-to-left handling, and the two retrieval bugs it
  exposed (corpus-wide document frequency, unindexed titles); the accessible
  chat interface with two layers of checking, one of them a real browser; a
  walkthrough whose expected output is executed by a test; and the fail-closed
  audit interlock, including the four findings the first real audit produced.

- 2026-08-15 — Session 3 (AI implementation session, clean-room implementation
  side). Input: the same specification and hygiene rules, this repository's own
  state, and the public Plumbline repository consumed as any other user would
  — its README, its gate documentation, and its source read the way a
  dependency's source is read before a pin is bumped. No other repository.

  Worked the list of open items. Built M6: a committed baseline and
  `audit_guard.py`, which fails on a score that decayed without breaching a
  floor — drilled for real, `GATE: PASS` and `GUARD: FAIL` on the same run.
  Made the disabled `multilingual` suite declare its gap as data the guard
  prints, and wrote out precisely where that fix belongs (Plumbline's
  `lexicons.py`, which this repository may consume and may not push to).
  Bumped the pin to `7071783` after reading the diff, and re-verified the
  interlock fails closed against it. Wrote the branch-protection ruleset as a
  committed, unapplied artifact, and said in three places that the gate is
  advisory until someone with admin rights applies it.

  Two things found along the way. `main` had been red since session 2: the
  interface announced the empty string into its live regions until
  `/strings.json` landed, which is silence in the two places the interface
  promises to speak — fixed, with a deterministic browser check. And the
  colloquial-recall refusal was worked to a conclusion rather than left as a
  note: the obvious fix, declared document aliases, was built, measured, and
  reverted, because it turns a visible refusal into an invisible wrong answer.

- 2026-08-15 — Session 4 (AI implementation session, clean-room implementation
  side). Input: the same specification and hygiene rules, this repository's own
  state, and the public Plumbline repository consumed as any consumer would —
  its README, and its source and history read the way a dependency's are read
  before a pin is bumped. No other repository, and nothing pushed to Plumbline.

  Three things, and the first of them is a negative result with the numbers
  published. `ck-015` was attacked as a ranking problem, as the open item said
  it was: three passage-level signals — the passage's own heading weighted in,
  the heading blended as its own field, a query-coverage factor — measured over
  twenty-one configurations against all 61 probes. Every one reverted, and the
  measurement disproved the diagnosis it was testing. The eligibility passage
  shares exactly one word with the question, and two passages in *other*
  documents hold that word plus another at the same length, so there is no
  reweighting that reaches it. Closed as a corpus fact rather than a scorer
  bug. Explain mode gained the term evidence that makes that reproducible in
  one command instead of by instrumenting the scorer by hand, and
  `tests/test_answering.py` now pins the evidence rather than the symptom.

  Second, the guard's ratchet worked one way. A fall failed the build; a rise
  printed a note that nothing made anyone action, and while it went unactioned
  the recorded bar sat below what the system did — the exact decay the guard
  exists to catch, coming through the door the guard left open. Both directions
  block now, labelled differently, and neither adopts a number by itself.

  Third, the pin bumped to `1b92472` and the interlock held: gate green, scores
  unchanged, the harness declining the numeric comparison because the judge
  hash moved, and fail-closed re-verified at exit 4. The bump closed the
  declared `multilingual` gap — upstream shipped Arabic by script, which is a
  better answer than the word list this repository asked for — and the new
  UNPINNED rule caught the newly enabled suite on its first outing, blocking
  until the baseline was adopted deliberately. Thirteen suites, none disabled.

  One correction to the record: the commit message on `db1b0c0` says 188 tests;
  the count at that commit was 187. Left in place rather than rewritten,
  because the pushed history is the provenance.
