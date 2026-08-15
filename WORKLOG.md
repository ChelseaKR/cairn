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
