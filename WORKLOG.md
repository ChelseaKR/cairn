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

  Third, the pin bumped twice — to `1b92472` and then to `a565b21`, upstream's
  head at the time of reading — and the interlock held both times: gate green,
  scores unchanged, the harness declining the numeric comparison on the first
  bump because the judge hash moved, and fail-closed re-verified at exit 4. The
  second bump touched no `src/` at all (demo data, tooling and docs only) and
  the gate returned the identical run id, which is the proof rather than the
  claim that it changed nothing. What to check in a pin review is now written
  in `plumbline.pin`. The first bump closed the declared `multilingual` gap —
  upstream shipped Arabic by script, which is a better answer than the word
  list this repository had asked for — and the new UNPINNED rule caught the
  newly enabled suite on its first outing, blocking until the baseline was
  adopted deliberately. Thirteen suites, none disabled.

  Found along the way, by the instrument built earlier in the session: a second
  wrong-paragraph case, `ck-022`, where the right document is chosen and the
  ranking among its four passages turns entirely on the word "out". Kept and
  named rather than tuned away, including the uncomfortable part — the audit
  passes that item, because no suite it runs can say "wrong paragraph".

  One correction to the record: the commit message on `db1b0c0` says 188 tests;
  the count at that commit was 187. Left in place rather than rewritten,
  because the pushed history is the provenance.

- 2026-08-16 — Session 5 (AI implementation session, clean-room implementation
  side). **Logged at the time as "Session 4", which the session above already
  was**; renumbered on 2026-08-15 with the original label kept here rather than
  erased. Input: the same specification and hygiene rules, this repository's own
  state, and the public Plumbline repository consumed as any other user of it
  would. No other repository, document or transcript was read.

  Three things, in the order they were asked for.

  **The audit grades the running engine now, not only a recording of it.** The
  pinned harness has an HTTP recorder, so `./plumbline-live.sh` starts
  `cairn serve`, has the harness ask all 26 committed questions over the
  socket and seal the answers, audits that bundle against the same floors, and
  `live_check.py` compares it to the committed evidence — provenance, question
  set, every answer byte for byte, and the served page against the interface
  snapshot the accessibility suite grades.

  Wiring it up found something on the first run, which is the whole argument
  for wiring it up: pointed at the served answer text, `citation_validity`
  scored **0.0000** on a system the offline audit scores 1.0000 on. The inline
  citation markers existed only inside `cairn record`. `/ask` returned the
  sources as structured metadata and the answer text with none in it, so the
  audit's perfect citation score described a string no client of the served
  interface could obtain — and a plain-text client got an answer with no
  sources at all. `Answer.cited_text` is the one definition now. The bundle
  came out byte-identical; only who can produce it changed. With that fixed,
  all suites score identically over the socket and every answer matches.

  It is an addition and not the gate, structurally: the pin does not name the
  live config, the live runner deliberately cannot resolve the harness (it
  borrows the checkout the gate verified), the `audit` job neither calls it nor
  waits on it, and the drift check itself also runs in the core test path
  against a loopback server with no harness and no network.

  **`ck-022` is scored rather than only documented.** The wrong-paragraph case
  the previous session found and could not express: Plumbline shipped
  `passage_attribution` for it during this session, so this adopted the suite
  rather than building a second one. Cairn's half was the evidence —
  `answering_sources` authored per item, and recorded `sources` widened from
  the quoted passage to every passage retrieval accepted, without which the
  suite has one candidate per item and the question is unanswerable by
  construction. Measured 0.9375 over 16 items, one failure, and the suite was
  more precise than the write-up: it reports `ck-022` as a *retrieval* failure,
  because the right passage never cleared the threshold. Every other suite
  came back identical to four decimals. `audit_guard.py` gained the
  denominator: a suite whose scored population moved against the baseline now
  fails in either direction, because a perfect score over a shrinking sample
  reads exactly like a check.

  **The open list is held against what is still true.** Six bullets of prose
  with nothing failing on them; now each is anchored to a fact, in both
  directions. Writing the anchors disproved one of the items: "cross-language
  fallback cannot cross scripts" is false. An Arabic question carrying the
  Latin program name is answered from the English document at 0.218; a Spanish
  paraphrase refuses at 0.145. The boundary is shared vocabulary, not the
  writing system — which is a worse limitation than the one recorded, because
  it falls on the person least likely to know the program's official name. The
  README also never said a screen-reader session has not happened while
  claiming WCAG 2.2 AA; the same test found that.

  Not done, deliberately: the branch-protection ruleset is still committed and
  **not applied**, and every document still says the gate is advisory. The
  screen-reader pass and generative mode remain declared gaps.

  Pin: `a565b21` → `d45ca40` → `f4b285e`, both bumps read as dependency
  upgrades and both behaviour-neutral here. 255 tests plus 49 browser checks;
  14 suites, none disabled.

- 2026-08-16 — Session 6 (AI review session, clean-room implementation side).
  Logged at the time as an unnumbered "Review pass", on the reasoning that two
  entries above were both "Session 4" and any number here would either repeat
  the collision or imply a session 5 that never happened. The second half of
  that was wrong — session 5 did happen, it was mislabelled — so the collision
  was fixed at its source on 2026-08-15 and this entry has the number it
  earned. The original wording is in the commit that added it, `4bf8376`.

  Input: the same specification and hygiene rules, and this repository's own
  state. No original repository, no other project's code. A quality pass
  rather than a milestone: nothing new was built, and five things were found.

  **`main` was red, and had been since the previous commit.**
  `tests/test_live.py::test_an_endpoint_it_cannot_read_exits_four` asked
  `./plumbline-live.sh` about a broken live config, but the runner read the
  pin and required a resolved harness checkout *before* it looked at its own
  configuration — so on a machine with no `.plumbline-cache`, which is every
  machine in the `core` job by design, it answered "the harness is not
  resolved" instead. The runner now finishes checking what it can check on
  its own before it needs anything outside the checkout, and a second test
  runs the same broken config with the cache absent and present and requires
  the same complaint from both, so the drill can no longer depend on whether
  someone had run the gate lately.

  **Four documented claims did not survive being checked.** `DESIGN.md` said
  `retrieval.max_passages` defaults to 2, in the configuration table and twice
  in prose, while the code, `cairn.toml` and `DESIGN.md`'s own audit-findings
  table say 1 — the value an audit finding moved it to. The calibration note
  quoted 0.187/0.148, which are the weight-1 numbers from the multilingual
  milestone; the shipped scorer measures 0.1965/0.1219, and every probe's fact
  passage ranks first rather than in the top two. The `README` quick-start
  showed a two-source answer to a question that cites one, and an English
  refusal in the wording the audit had already replaced — the version that
  said it had no source without saying it could not help. And
  `cairn/language.py` told operators to add right-to-left codes to
  `[language] rtl`, a configuration key that does not exist and, per
  `DESIGN.md`, deliberately never will; the unused `extra_rtl` parameter that
  made it look plausible is gone.

  **Two checks that could pass without checking.** The README is now executed
  like the walkthrough, under a rule loose enough for wrapped and elided
  prose — every word shown must be a word the command printed, in order —
  which is what caught two of the claims above. And the contrast suite graded
  a colour pair in both presentations without anything requiring the dark
  presentation to define its own colours: an unoverridden token silently keeps
  its light value, and the light pair passes by construction. Every colour the
  pairs use must now be re-themed.

  **Four browser checks asserted `true`.** Each was backed by a preceding
  wait, so none was empty, but one of them — "an empty question is reported
  without a request" — never checked the second half of its own description.
  It counts requests to `/ask` now, and fails if the script stops preventing
  the form's native post. 50 browser checks, up from 49; 260 tests, up from
  255.

  Not done: the branch-protection ruleset is still committed and **not
  applied**, the screen-reader pass has still not happened, and `ck-015` and
  `ck-022` behave exactly as recorded.

- 2026-08-16 — Session 7 (AI review session, clean-room implementation side).
  Input: the same specification and hygiene rules, and this repository's own
  state; plus the pinned Plumbline checkout in `.plumbline-cache/`, read the
  way a dependency's source is read. No original repository, no other
  project's code, nothing pushed anywhere. A second quality pass: it worked
  the list session 6 left, and then kept going on the same two questions —
  which checks cannot fail, and which claims are not true.

  **A reason for not doing something, which turned out to be false.**
  `Answer.cited_text` is documented as the form for a client that cannot
  render a sources list, and it dropped `answer.notice` — so a cross-language
  answer reached such a client as an English passage in a Spanish session with
  nothing saying why. That is the same defect as the missing citation markers
  the live audit found, one field over, and the previous pass left it on the
  grounds that fixing it moves the bundle hash and every score. It does not:
  no item in the committed question set reaches the cross-language path, so no
  recorded answer carries a notice, and the bundle re-records byte-identical
  at `3222a884…` with the gate returning the same run id `54a2e2945ef4242b`.
  Checked by running it, not by reasoning about it.

  That measurement is itself the finding: **the audit has never graded a
  cross-language answer.** DESIGN.md says the corpus asymmetry "is what
  exercises the cross-language path", and it does exercise the code — the
  tests and the browser checks both drive it — but not the evidence. It is a
  declared open item now, with a test that fails the day an item does cross.
  Adding one is left undone deliberately: it moves the dataset hash, the
  baseline and several published figures at once, and `multilingual` would
  score it zero, which is the correct finding and a reviewed diff of its own.

  **One configuration could produce a grounded answer with no source.**
  `Config(max_passages=0)` composed zero passages while the trace still said
  passages had been accepted, so `kind` stayed `"grounded"`, `grounded` stayed
  true in the payload, and the answer was empty with nothing cited. That is
  the one outcome this project says it does not have, reached through the
  constructor rather than the corpus, because the bounds were checked in
  `load_config` and not on the type — and this is a reference implementation
  whose whole invitation is that somebody imports it. There were no tests over
  configuration at all. The bounds live on `Config` now.

  **The pin was bypassable by a variable this repository never sets.**
  `PLUMBLINE_SRC` skips resolution entirely and the runner warns and proceeds;
  the workflow said "never PLUMBLINE_SRC" in a comment and nothing enforced
  it, while the variable can arrive from a repository variable or a runner's
  own profile. The runner is vendored byte for byte, so the fix is not in the
  file: every gate invocation now runs under `env -u PLUMBLINE_SRC`, drilled
  both ways. And "vendored verbatim" — claimed in three places, checked
  nowhere — is now diffed against the resolved harness in the one job that
  has one.

  **Three checks that could pass without checking**, all of the same shape: a
  loop over a population that can be empty. Focus visibility was checked in
  the light presentation only while the file's own header claimed both; the
  minimum-target-size check iterated whatever `min-height` rules it found and
  passed when it found none; the check on the authored `answering_sources`
  ground truth skips items with no dollar amount and would skip all of them if
  amounts were written differently. Each now requires its population. The
  guard's coverage inventory had the same ambiguity from the other side —
  printing nothing when no suite held items out, which is what a renamed
  harness key would also print — and says it in words now.

  **An indented heading rendered its own marker.** `cairn/ui/page.py` stripped
  `#` off the raw line and `app.js` stripped the whitespace first, so the two
  renderers disagreed about `  ## Something` — one page showed the marker and
  the other did not, against a comment in `app.js` saying they produce
  identical markup. No corpus document is indented, which is why nothing was
  failing. The rule is two named patterns now, spelled identically in both
  files, with a test on the spelling.

  Also corrected: a comment in `tests/test_ui.py` still carried the
  "cross-language fallback cannot cross scripts" claim this repository
  disproved two sessions ago, and `workflow_job()` in `tests/test_live.py`
  read comments as code — a sentence explaining why the audit job does not
  call the live runner counted as the audit job calling it.

  **The Session 4 collision is fixed at its source.** Session 6 declined to
  number itself because two entries above it both said "Session 4" and a
  number here would either repeat that or imply a session 5 that never
  happened. The second half was wrong: session 5 did happen and was
  mislabelled. The 2026-08-16 entry is Session 5 with its original label
  recorded in it, session 6 has the number it earned, and nothing is erased —
  the original wording of both is in the commits that wrote them.

  **Seven documented claims did not survive a systematic re-check**, done by
  re-measuring rather than re-reading. The grounding, citation and refusal
  path came back clean: every constant, the calibration band, both worked
  ranking examples and all the corpus counts are exactly as written. What had
  rotted was around the audit. The README published a gate transcript with a
  run id from before the baseline was last regenerated, in a fence nothing
  executes — the run id is elided in both documents now, because it hashes
  four inputs and nothing offline can recompute it, and the dataset id, which
  *is* the bundle's own hash, has a test on it. Five floors in
  `plumbline/target.toml` were non-default with no comment, against this
  project's own stated rule, and one of them — `fairness` at 0.80 against the
  harness's 0.85 — is looser than the default with no reason on record; the
  comment says that rather than inventing one, and the decision is left to
  whoever set it. `docs/demo.md` claimed every command on it was executed
  while three sections are unexecuted `text` fences, and claimed "no network"
  on a page whose audit step says it needs one. Both drill transcripts were
  re-executed rather than re-typed, and the first came back bigger than it was
  written: four regressions, not three, plus four coverage findings the guard
  could not report when the block was captured. Two more: "two live regions"
  is three, and progress goes to `#status` rather than the log; "the pin
  bumped three times" is six, and was never a count of anything, since exactly
  one bump had landed when the row was written.

  280 tests plus 62 browser checks; 14 suites, none disabled; gate and guard
  green on the same run id as before, and the live check still byte-identical
  over the socket. Nothing in this session moved a score, which is the point:
  every fix here was either outside the measured path or provably neutral on
  it.

  Not done, still: the branch-protection ruleset is committed and **not
  applied**, the screen-reader pass has not happened, `ck-015` and `ck-022`
  behave exactly as recorded, and the browser checks' own dependencies
  (`axe-core`, `playwright`) float on caret ranges with the lockfile
  gitignored — the auditor is pinned to a commit and the rule set that grades
  the interface is not.

- 2026-08-16 — Session 8 (AI remediation session, clean-room implementation
  side). Input: the same specification and hygiene rules, this repository's
  own state, and the pinned Plumbline checkout in `.plumbline-cache/`, read
  the way a dependency's source is read. No original repository, no other
  project's code, nothing pushed anywhere. Session 7 left four things as
  maintainer decisions and they were approved; this session made them, then
  kept going on the same two questions.

  **The four.** `fairness` is back at the harness's default of 0.85 — it was
  0.80, the only floor in the file looser than its default and the only one
  with no reason on record at all. Measured 0.9364, so the loosening was never
  load-bearing, which is exactly why restoring it costs nothing and is the
  right resolution. Every other non-default floor now carries a
  `floor_reason`, and there are **six** of them, not the five session 7
  counted: `accuracy` at 0.35 against a default of 0.75 has a long comment
  that never says it is not the default. A rule policed by reading gets the
  count wrong, so `audit_guard.py` enforces it now, against defaults parsed
  out of the pinned harness's own source rather than out of a number typed
  into Cairn's config.

  **`ck-027` is in the evidence set.** Twenty-six recorded answers, none of
  them cross-language, so no audit report this repository had ever published
  said anything about the behaviour the README spends three paragraphs on —
  and that is how `Answer.cited_text` came to drop the notice for a whole
  milestone with every check green. It is `ما هي بطاقة GoPass؟`, answered from
  the English-only transit document under an Arabic notice. The dataset hash
  moved `3222a8849261` → `81ca3d7003f0`, the baseline was regenerated
  (`123b2569cb8a46ba` → `38cd1ce582a57150`), the run id is `f03f61f1b9bbb3e8`,
  and every score that moved is tabulated in DESIGN.md, "The cross-language
  path, in the evidence". `multilingual` scores the item **0.0000** — asked in
  `ar`, answered in `en` — which was predicted and is recorded as a finding
  rather than avoided; the suite has room for exactly one such item before the
  floor bites, and that is a new open item with the three ways out named.
  `groundedness` and `citation_accuracy` fell to 0.9714 because the notice is
  Cairn's own words and appears in no source, which the `cited_text` docstring
  predicted before the item existed.

  **The notice was wrong in a way no default configuration shows.** It read
  the first accepted passage's language while composition quotes
  `max_passages` of them, so at 2 an Arabic reader could be handed a Spanish
  passage and an English one under a notice naming Spanish alone and calling
  it "the only source" — two false statements in the sentence whose whole job
  is to say what language the answer is in. It now describes the passages
  actually quoted, and the predicate is "a foreign passage was quoted" rather
  than "the widened pass won", which was a proxy that held only through an
  unstated property of the scorer.

  **`Answer.cited_text` dropping the notice was already fixed** — session 7's
  own last commit did it. The brief for this session said otherwise; the code
  and the test were both already there. Recorded here because a remediation
  list that is wrong about what is broken is worth saying out loud.

  **Bounds at the edge, generalised.** Session 7 fixed `Config(max_passages=0)`
  by moving the bound onto the type and noted that the shape would recur.
  It did, four times. `compose()` takes `max_passages` directly and had no
  bound of its own, so the promise was one import away from being false again.
  `Answer` is a public frozen dataclass that serializes `"grounded": true` off
  `kind` alone, with nothing stopping a hand-built grounded answer with no
  sources — the same defect with the config layer removed; it validates
  itself now, in both directions, including that a refusal carries no notice.
  `Config.default_lang` was unvalidated while both edges around it were
  guarded: `[language] default = "fr"` produced a grounded answer labelled
  `lang: "fr"` carrying an English cross-language notice, and with `"he"` an
  RTL layout around an English body. And `Index.stats_for` fabricated empty
  statistics for a language it had never heard of, which gives every term an
  IDF of exactly 1.0 — a passage in an unlisted language scored on raw overlap
  with no stopword suppression, clearing a threshold calibrated against
  weighted scores. `Index` validates on construction now.

  **Two corpus fields that could make a grounded answer lie.** A doc id was
  unvalidated against the citation grammar it has to satisfy, so
  `2024-winter-credit` or an Arabic-script id emits markers nothing recognises
  as citations — every grounded answer from that document grades as uncited —
  and `a#b` and `a.b` are different documents that emit the same marker. And
  `lang: en-GB` was English for layout and a separate language for retrieval,
  because `direction_of` normalised subtags and retrieval compared the string
  exactly: one front-matter typo, a permanently false "the only source I have
  for this is written in another language (en-GB)" on every answer from it.

  **A character of somebody's benefit information.** `#` opened a heading
  whenever a line started with one, which is not Markdown: `#1 priority is
  rent` rendered as **1 priority is rent** in both renderers. Both tests that
  covered it built their expected value by running the stripping regex over
  the input, so the bug was the specification and neither could fail. And
  `page.py` split lines with `splitlines()` while `app.js` split on `"\n"`, so
  U+2028, form feed and friends — routine in Word and PDF extractions —
  rendered server-side as characters the cited source does not contain. The
  parity test compared the two regexes and not the splitting rule.

  **The server could answer the wrong question.** An oversized body was
  refused without being read, and under HTTP/1.1 the unread bytes were parsed
  as the next request line: a client that pipelined a real question behind an
  oversized one got `501 Unsupported method ('question=aaaa…')` and never got
  its answer — with a prefix of the question written to the log of a server
  whose docstring says it logs nothing about the questions people ask. A
  non-numeric `Content-Length` killed the handler thread with a traceback.
  Both fixed, both with tests over a raw socket.

  **Checks that could not fail.** The biggest: the list of suites came
  entirely from `plumbline/target.toml` and `plumbline/baseline.json`, so
  deleting `[suites.privacy]` from both in one commit deleted it from the
  universe as well — the gate would say "13 suites passed", the guard would
  say nothing moved, and every test over the committed artifacts would agree.
  The universe comes from the pinned harness now. `multilingual` was still
  carrying `gap` and `fix_belongs_in` from the milestone it was disabled in,
  which would have pre-satisfied the "a disabled suite must explain itself"
  check for whoever disabled it next. `expected_check_names()` dropped any CI
  job with no explicit `name:`, and a job outside the expected set need not be
  in the ruleset — the exact hole that file exists to close, inside the thing
  measuring it. `test_index_round_trips` asserted `len(x) == len(x)` and
  `all([])`, both true on an index that read back empty, in the only test of
  the round trip. `test_the_guard_cannot_be_softened` looked for
  `continue-on-error` only in the half of the step before `run:`. The
  gap-closure check skipped wholesale the moment any gap existed. A refusal's
  contact line was asserted against the same lookup that produced it, so an
  Arabic refusal ending in the English contact would pass. `split("function
  say(")` returned the whole file when the anchor was renamed. And the
  duplicate-harness-version scan dropped any file it could not decode.

  **`load_config` was less safe than no config file at all.** An absent
  `[refusal.contact_by_language]` was passed through as `{}`, overriding the
  type's per-language defaults — so a `cairn.toml` setting only
  `[corpus] path` ended an Arabic refusal in English, while no file at all
  ended it in Arabic. Absent now means default; and an operator who sets a
  single `contact` and no table keeps it for every language rather than having
  Cairn's fictional Spanish and Arabic phone numbers filled in around it.

  **axe-core is pinned.** The auditor that grades the engine is pinned to a
  commit and says so at length; the rule set that grades the interface was on
  a caret range with the lock file gitignored. Exact versions, committed lock,
  `npm ci` in CI, `axe-core` named directly rather than left transitive, and
  a11y.mjs asks the page which version actually graded it. The check count is
  pinned too — a dropped check prints as a smaller green total — and so is the
  README's test count, which nothing held.

  **A published measurement that was half a success.** The README said
  `GoPass كم سعرها؟` "is answered from the English document… the fallback
  crosses scripts perfectly well". It is answered from the document's opening
  paragraph, which contains no price: "GoPass" is the only term that survives
  the crossing, all four passages contain it, and length decides the rest.
  Crossing the script is not answering the question. Corrected in both
  documents, and it is why `ck-027` asks what the pass *is*.

  309 tests plus 63 browser checks; 14 suites, none disabled; gate PASS
  (dataset `81ca3d7003f0`, run `f03f61f1b9bbb3e8`), guard PASS against
  baseline `38cd1ce582a57150`, live check byte-identical over the socket for
  all 27 answers.

  Not done, still: the branch-protection ruleset is committed and **not
  applied**, the screen-reader pass has not happened, `ck-015` and `ck-022`
  behave exactly as recorded, and the index carries no fingerprint of the
  corpus it was built from — edit a document without re-indexing and Cairn
  quotes the old text under a citation that now resolves to different content.
  That one is named rather than fixed: a fingerprint changes the index format
  and the line the walkthrough prints, and it deserves its own diff.

- 2026-08-16 — Session 9 (AI implementation session, clean-room implementation
  side). Input: the same specification and hygiene rules, this repository's own
  state, and the pinned Plumbline checkout in `.plumbline-cache/`, read the way
  a dependency's source is read. Nothing pushed anywhere. Session 8 named three
  things and left them; this session did all three, then kept hunting the same
  two defect classes, then took on a published evidence page and the metadata a
  reference implementation needs to be cited at all.

  **The index knows what corpus it was built from.** The largest item session 8
  left. Edit a document, forget to re-index, ask a question: Cairn quotes the
  paragraph as it was and cites the document as it is, and nothing anywhere can
  tell, because everything downstream of the index agrees with the index —
  including `cairn record`, so the audit grades the same stale answers. The
  index now carries a SHA-256 of the corpus files it read, the format version
  moves 2 → 3 so an index that cannot say what it was built from is refused
  rather than trusted, and `read_index` takes the corpus directory as an
  argument **with no default**: an optional check is a check a caller forgets,
  and here a caller is an agency's deployment. A missing corpus is a refusal
  too, and that is the arguable half — an index whose corpus is not on disk
  cannot be shown to be current, and this project does not answer from a state
  it cannot check. The walkthrough prints the fingerprint, and the refusal
  transcript on it was captured by editing a document and reverting it rather
  than typed.

  Written so it can fail, and shown failing. Deleting the check makes four
  tests red, one of them by timing `cairn serve` out rather than hanging.
  Two versions of the fingerprint were written and both were caught by the
  tests before they were caught by review: one that dropped file names passed
  everything until a rename that kept its sort position and its length, and one
  that hashed only `*.en.md` passed until the edit case was applied to every
  document rather than to one.

  **A one-passage language is retrievable again.** `MAX_DF_RATIO` suppresses a
  term in more than half a language's passages. With one passage every term
  qualifies, so the language scores 0.0000 against every question in every
  language, including one that quotes it verbatim — measured with a single
  Vietnamese paragraph. The cross-language fallback cannot rescue it either,
  because the fallback scores each passage against its own language's
  statistics. Documented and left alone last milestone on the grounds that
  nothing crossed languages; `ck-027` exists now, so it was reconsidered and
  changed. The floor is skipped only where it would leave no term standing,
  which is where it has stopped being a statistic; at two passages it bites
  again and the docstring says so rather than claiming more. Provably neutral:
  `cairn record` re-records byte-identical, dataset `81ca3d7003f0`, run
  `f03f61f1b9bbb3e8` and baseline `38cd1ce582a57150` all unmoved.

  **`ck-027`'s zero: the third way out, taken.** Lowering the `multilingual`
  floor is refused — it would buy coverage of a path Cairn is confident about
  by spending the sensitivity that catches a system silently answering a
  Spanish speaker in English. Teaching the harness is correct and is not
  Cairn's to do at a pin, and the version worth filing is narrower than the
  sentence that was written down. So the path is audited by exactly one item,
  and a second one is a gate failure rather than a silent dilution. The
  arithmetic published for that second item was wrong — 26 of 27 plus one
  failing item is 26/28, not the 25/28 in the document — and it is computed
  from the committed baseline now instead of typed.

  **Nine more checks that could not fail**, found by an audit of the suite
  rather than by working on the code. The two that mattered: the corpus-heading
  check built its expected value by running `ATX_MARKER` over the input, which
  is the third instance of a defect this repository has twice written up as
  fixed — widen the pattern by one character and every heading renders with its
  first letter deleted, so a grounded answer no longer says what the cited
  passage says, and the test passed. And `axeScan` reported "clean" for a scan
  that graded nothing: `withTags` filters axe's rule set, and a major version
  that renamed a tag would have left all six scans green with zero rules run,
  the pinned check count intact and the conformance claim resting on air. Also:
  a contrast check whose population came from the list it was auditing, so a
  failing pair could be fixed by deleting it; the CLI's refusal trace asserted
  with `all([])`; three loops a refusal would empty; `[] == []` over the
  evidence bundle; a README block that shows no output and is therefore checked
  against nothing; the "the gate is advisory" check satisfied by the wrong
  document, so the item could be deleted from the open list without failing;
  and the guard's gap-declaration check, which iterates nothing today and would
  iterate nothing just the same if the helper had stopped finding gaps — it has
  a positive control now.

  **A test that skipped every time in CI while saying it did not.** The one
  check holding `plumbline/target.toml`'s floors against the pinned harness's
  own defaults skips without a resolved harness — and the only job running the
  unit suite is `core`, which *fails if the harness cache exists at all*. So it
  ran on a laptop and nowhere else, under a docstring saying otherwise. The
  `audit` job runs that module explicitly now, after the step that resolves the
  harness, and a test holds the workflow to it.

  **A published evidence page, and the check that keeps it honest.**
  `site/index.html` is committed, rendered by `site_build.py` from the evidence
  bundle and the baseline, and served by GitHub Pages once somebody enables it
  in settings. It leads with a refusal, then `ck-027` — the answer Cairn's own
  auditor scores as a failure — then the baseline table. Two checks, and the
  distinction is the point: re-render-and-diff catches a hand edit and a
  rebuild that never happened, and cannot catch a generator that invents,
  because it asks the generator; a parse of the committed HTML held against the
  JSONL catches that. Demonstrated by making the generator print a friendlier
  refusal: the diff check passed and the parse check failed, which is the whole
  argument for having both. The deploy uploads the file and never builds it,
  every action is pinned to a commit, and both checks also run offline in
  `core`, so a drift fails the pull request before it can reach a deploy.

  **Citable.** `CITATION.cff`, a changelog, and the version bumped
  `0.1.0.dev0` → `0.1.0` so the tag a reader cites means something. The tag is
  **not cut** — tagging is a push. Four records of the version now, held
  together by a test, on this repository's own argument that a version recorded
  in two places will disagree with itself. The version appears nowhere in the
  evidence bundle, so the bump moves no hash.

  356 tests plus 63 browser checks; 14 suites, none disabled; gate PASS
  (dataset `81ca3d7003f0`, run `f03f61f1b9bbb3e8`), guard PASS against baseline
  `38cd1ce582a57150`, live check byte-identical over the socket for all 27
  answers, and the recorded bundle byte-identical to the committed one after
  every change in this session.

  Corrected here: session 8's own summary line said "309 tests" while the
  README it had already updated said 313, and 313 is what the suite discovered.
  The README figure has a test under it and the worklog line did not, which is
  the whole reason the discrepancy is in this direction.

  Not done, still: the branch-protection ruleset is committed and **not
  applied**, GitHub Pages is **not enabled** so the evidence page's URL is a
  404, no `v0.1.0` tag exists, the screen-reader pass has not happened, and
  `ck-015` and `ck-022` behave exactly as recorded.

- 2026-08-22 — Session 10 (AI implementation session, clean-room implementation
  side). A correction, and the thing it corrects.

  **The evidence page has been live since 2026-08-16.** The session 9 entry
  above, the README and a comment in `pages.yml` all said GitHub Pages was
  *not* enabled and the page's URL was a 404. Pages was enabled that same day
  — the first successful `pages` deploy is timestamped 2026-08-16 — and
  https://chelseakr.github.io/cairn/ returned 200 when checked today. The
  sentence in the README was true when written and stayed six days after it
  stopped being true. Nothing in the test suite could have caught it: whether
  a URL serves is a property of GitHub's side, not of a checkout, which is the
  same reason the branch-protection item lives under "the one thing this
  repository cannot do for itself". Corrected in all three places; the
  session 9 entry is left as written, because that is what was true then.

  Not done, still: the branch-protection ruleset is committed and **not
  applied**, no `v0.1.0` tag exists, the screen-reader pass has not happened,
  and `ck-015` and `ck-022` behave exactly as recorded.

- 2026-08-22 — Session 11 (AI implementation session). Input: a stashed,
  uncommitted six-feature expansion built in an earlier session against an
  older `main`, consumed as source material rather than applied wholesale —
  `main` had since gained 24 merged pull requests the stash never saw,
  including the branch-protection ruleset actually being applied and
  `v0.2.0` actually being tagged and published. Landing all six at once
  would have meant six different concerns arriving as one diff; landed
  first, and alone: hybrid retrieval.

  `cairn/embed.py`: deterministic hashed character-n-gram embeddings —
  BLAKE2B feature hashing, never Python's salted `hash()`, so the vector is
  reproducible across processes (a test runs a child interpreter under three
  different `PYTHONHASHSEED` values to prove it). Fused into `cairn.retrieve`
  behind `retrieval.dense_weight`, default 0. Two safety properties, both
  tested: the dense channel never ranks a passage sharing zero lexical terms
  with the question, and at `dense_weight == 0` the fused scorer is
  byte-for-byte the plain lexical one — confirmed by `cairn record
  --diff-against plumbline/bundle` reporting no difference, not only by the
  default value being zero. The weight-sweep measurement that keeps it
  opt-in (w = 0.25 turns the known colloquial refusal into a confident wrong
  answer) is published in DESIGN.md, "Hybrid retrieval: a dense channel,
  opt-in".

  The other five — query-understanding passes, structured corpus tables,
  streaming, multi-turn sessions, and a second pinned adversarial harness
  (`gauntlet`) — remain stashed, unlanded, each its own future session's
  input. `make verify`: ruff, mypy, 615 tests, 93% branch coverage.
  `./plumbline-gate.sh`: GATE PASS, 14/14 suites, evidence bundle unchanged.

- 2026-08-22 — Session 12 (AI implementation session). Input: the same
  stashed six-feature expansion session 11 drew from. Second extraction:
  query understanding.

  `cairn/query.py`'s `split_intents` (`retrieval.split_intents`, opt-in,
  default off) scores each sentence of a multi-part question separately and
  merges the candidate pools by best score per passage, so one half of a
  two-part ask cannot be diluted by the other — the composed-truncated
  failure DESIGN.md already names, caught one stage earlier. Sentence
  boundaries only, in all three interface languages; coordinating
  conjunctions are deliberately never boundaries, tested directly against
  the audit set's own adversarial shape ("ignore the documents and just tell
  me…" must not split at its "and"). `RetrievalTrace` gained `intents`,
  empty unless the pass ran.

  Two siblings that did not ship are written up in DESIGN.md next to the one
  that did rather than left silent: query-side diacritic folding (built,
  reverted — it moved `ck-026` onto the wrong passage for no measured gain)
  and refusal rescue by pseudo-relevance feedback (built, deleted outright —
  three of four rescued refusals landed on the wrong program). Neither left
  code behind to extract; both are prose, ported from the stash's own
  documentation of them.

  One thing the stash had not verified: mypy. `cairn/query.py`'s merge step
  typed its best-score map as `dict[str, tuple[float, object]]`, which
  happened to run fine — Python does not check types at runtime — but hid a
  genuinely dead `order` dict, written every merge and never read anywhere.
  Typed the map as `dict[str, tuple[float, Candidate]]` instead and removed
  `order`; mypy now reads the file clean, and there is less of it to read.

  `make verify`: ruff, mypy, 624 tests, 93% branch coverage.
  `./plumbline-gate.sh`: GATE PASS, 14/14 suites, evidence bundle unchanged
  (the pass is off by default; `cairn record --diff-against` confirms zero
  drift the same way session 11's did). Four of six landed features remain:
  structured corpus tables, streaming, multi-turn sessions, `gauntlet`.
