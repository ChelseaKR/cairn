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

  277 tests plus 62 browser checks; 14 suites, none disabled; gate and guard
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
