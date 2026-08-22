# The demo, end to end

Every command in a ```console fence below is run exactly as written, from a
clean checkout, with no network, no API key, and no install step. The output
shown under those is the output you get — literally: `tests/test_docs.py` runs
them in a temporary directory and fails if a single character differs.
Documentation that drifts from behavior is a defect, so it is treated as one.

Sections 8, 9 and 10 are fenced as ```text instead, and are **not** executed:
`cairn serve` never returns, and the audit needs the network the first time to
fetch the pinned harness. Their transcripts are elided with `...` and are
illustrations rather than recordings — which is why this page says which fence
you are looking at rather than claiming every line on it is checked.

One more ```text fence sits in section 1, for a different reason: producing
that output means editing a corpus document, and a page executed against the
shipped corpus must not. It is a recording rather than an illustration — it
says how it was captured — and the behaviour it shows has its own tests.

Requires Python 3.11 or newer. Nothing else.

## 1. Build the index

```text
$ git clone https://github.com/ChelseaKR/cairn.git
$ cd cairn
```

```console
$ python3 -m cairn index
Indexed 40 passages from 10 documents (10 marked synthetic) in 3 languages [ar, en, es] -> .cairn/index.json
Corpus fingerprint: 5bfa70e8cad4 (corpus/demo)
```

The count of synthetic documents is not decoration. Every file in the bundled
corpus is invented, and the label travels from the front matter of each
document into the tooling output rather than living only in a README.

Re-running `index` on an unchanged corpus rewrites the same bytes: the index is
serialized with sorted keys, a fixed layout, and no timestamps, so idempotency
is checkable with a file hash rather than argued for. The test suite checks it
that way.

The fingerprint on the second line is a hash of the corpus files this index was
built from, stored inside the index. `ask`, `serve` and `record` all recompute
it before they answer anything, and refuse if it has moved:

```text
$ python3 -m cairn ask "How much is the monthly grocery allowance for one person?"
cairn: error: the corpus at corpus/demo has changed since the index was built
(corpus 918154360e3e, index 5bfa70e8cad4). Answering now would quote the text
the index holds and cite a document that no longer says it. Re-run `cairn index`.
```

That is real output, captured by appending one paragraph to
`corpus/demo/grocery-allowance.en.md` and reverting it. It is hard-wrapped and
fenced as `text` rather than `console` because reproducing it means editing a
corpus document, which the executed walkthrough must not do;
`tests/test_ingestion.py` and `tests/test_cli.py` make the edit in a temporary
copy and hold every subcommand to the refusal. Edit a document without
re-indexing and the alternative is worse than an error: Cairn goes on quoting
the paragraph as it was and citing the document as it is, and every surface
downstream of the index — the inline marker, the sources list, the recorded
evidence bundle — agrees with it.

## 2. Ask something the corpus covers

```console
$ python3 -m cairn ask "How much is the monthly grocery allowance for one person?"
## How much you get
A one-person household receives $212 per month. Each additional household
member adds $118 per month. For example, a household of three receives $448
per month.

Sources:
  [1] Fresh Start Grocery Allowance (grocery-allowance-en#2)
```

The answer is the cited passage, verbatim. Nothing is paraphrased or
summarized, so `$212` appears in the answer for exactly one reason: it appears
in `grocery-allowance-en#2`. Every source is a document title plus a stable
identifier an operator can open the document and count to.

One passage by default. `retrieval.max_passages` raises that, and section 7
shows how to see what a lower value is dropping.

## 3. Ask something it does not cover

```console
$ python3 -m cairn ask "Can you help me renew my drivers license?"
I don't have a source for that, so I can't help with this question. None of the official documents this assistant is allowed to answer from cover it, and I won't guess.
For help from a person, contact the Harbor County Community Assistance office at 555-0142 (a fictional demo contact; operators must configure their own).
```

No sources, no hedged guess, no partial answer assembled out of the
nearest-looking passage. The exit status is 0: refusing without evidence is
the assistant working, not failing, and `--json` reports it as
`"kind": "refusal"` so refusals can be counted rather than inferred from an
error rate.

## 4. Ask in another language

```console
$ python3 -m cairn ask "Cuanto cubre la subvencion de alivio de vivienda?"
## Cuánto cubre la subvención
La subvención cubre hasta $3,500 de alquiler no pagado. Se paga una vez por
hogar; un hogar que ya recibió la subvención no puede recibirla de nuevo
durante 36 meses.

Fuentes:
  [1] Subvención de Alivio de Vivienda de Harbor (housing-relief-es#2)
```

The question's language was determined from the corpus's own vocabulary — no
model, no language-detection dependency — and the answer cites Spanish
sources. `--lang es` states it outright if you would rather not rely on that.

## 5. Ask in Arabic

```console
$ python3 -m cairn ask "كم قيمة رصيد المرافق الشتوي شهريًا؟"
## قيمة الرصيد
تحصل الأسرة المؤهلة على رصيد قدره $95 شهريًا من نوفمبر حتى مارس، بحد أقصى
$475 في الشتاء الواحد. أما الأسر التي تعتمد على الكهرباء في التدفئة فتحصل على
$40 إضافية شهريًا.

المصادر:
  [1] ⁨رصيد هاربر الشتوي لفواتير المرافق (utility-credit-ar#2)⁩
```

The source identifiers in that list are wrapped in Unicode bidi isolates
before printing. A terminal resolves direction the same way a browser does,
and without isolation the trailing `)` of `(utility-credit-ar#2)` visibly
migrates to the wrong end of an Arabic line. (This is why the raw markdown of
this page contains invisible control characters inside the Arabic block —
leave them alone.)

## 6. Ask about something the corpus has in only one language

```console
$ python3 -m cairn ask --lang es "How much does the GoPass cost per year?"
La única fuente que tengo para esto está escrita en otro idioma (⁨English⁩). Se cita a continuación tal como fue publicada.

## The discount and the fee
GoPass holders pay 50 percent of the standard fare on every ride. The pass
costs $20 per year, and the fee is waived for riders enrolled in the Fresh
Start Grocery Allowance.

Fuentes:
  [1] Harbor GoPass Reduced Fare Program (transit-pass-en#2)
```

The transit document exists only in English, which is what agency translation
backlogs actually look like. Cairn says so in the language you asked in, then
quotes the English source exactly as published. It does not translate it: a
translated policy amount is an unsourced policy amount. Set
`[language] cross_language_fallback = false` to refuse instead.

## 7. Find out why an answer was wrong

```console
$ python3 -m cairn ask --explain "What vaccinations does my dog need?"
=== retrieval trace ==========================================================
Question:  What vaccinations does my dog need?
Index:     40 passages from 10 documents (.cairn/index.json)
Threshold: 0.165 (retrieval.threshold)
Language:  en (vocabulary)
           corpus vocabulary coverage: en 0.40, es 0.00

Attempt 1 (restricted to 'en'): 16 passages scored, 24 excluded, 4 candidates
  question terms:      does, dog, need, vacci, what
  in no passage:       does, dog, vacci
   1  0.069  reject  grocery-allowance-en#3  [en] Fresh Start Grocery Allowance
          ## Income limits: who can apply Your household's gross monthly income must be at or bel…
          matched 1/5: need
   2  0.044  reject  utility-credit-en#2     [en] Harbor Winter Utility Credit
          ## What the credit is worth An eligible household receives a credit of $95 per month fr…
          matched 1/5: what
   3  0.041  reject  utility-credit-en#4     [en] Harbor Winter Utility Credit
          ## Applying, and what a decision takes Applications open on October 1 and close on Febr…
          matched 1/5: what
   4  0.041  reject  grocery-allowance-en#4  [en] Fresh Start Grocery Allowance
          ## How to apply and what happens next Apply online, by mail, or in person at any Commun…
          matched 1/5: what

Attempt 2 (widened to every language): 40 passages scored, 0 excluded, 4 candidates
  question terms:      does, dog, need, vacci, what
  in no passage:       does, dog, vacci
   1  0.069  reject  grocery-allowance-en#3  [en] Fresh Start Grocery Allowance
          ## Income limits: who can apply Your household's gross monthly income must be at or bel…
          matched 1/5: need
   2  0.044  reject  utility-credit-en#2     [en] Harbor Winter Utility Credit
          ## What the credit is worth An eligible household receives a credit of $95 per month fr…
          matched 1/5: what
   3  0.041  reject  utility-credit-en#4     [en] Harbor Winter Utility Credit
          ## Applying, and what a decision takes Applications open on October 1 and close on Febr…
          matched 1/5: what
   4  0.041  reject  grocery-allowance-en#4  [en] Fresh Start Grocery Allowance
          ## How to apply and what happens next Apply online, by mail, or in person at any Commun…
          matched 1/5: what

Stage 1 - retrieval: FAILED (below-threshold)
  4 candidates were scored and none cleared the 0.165 threshold. The best,
  grocery-allowance-en#3, scored 0.069 and was short by 0.096 on 1 of 5
  question terms (need). No passage searched contained does, dog, vacci — that
  part of the question is a corpus coverage gap, not a threshold setting.
Stage 2 - answer: NOT REACHED (no-evidence)
  The answer stage was handed no passages, so it refused. It could not have
  produced text here; look upstream at retrieval.

Verdict: NOT GROUNDED - refusal, no sources.
Diagnose at: retrieval.
==============================================================================

I don't have a source for that, so I can't help with this question. None of the official documents this assistant is allowed to answer from cover it, and I won't guess.
For help from a person, contact the Harbor County Community Assistance office at 555-0142 (a fictional demo contact; operators must configure their own).
```

Read the last line first. A bad answer has two possible authors and this says
which one you have:

- **Retrieval failed** — nothing cleared the gate, so the answer stage was
  never given anything to work with. Fix the corpus or the threshold.
- **Retrieval succeeded and the answer is still wrong** — the report says
  `composed-truncated` and names the accepted passages that
  `retrieval.max_passages` dropped. Fix the composition setting.

Both retrieval attempts are shown, including the widened cross-language one,
so the language filter is visible rather than silently narrowing a candidate
list you are trying to debug.

Then read the term lines. A score tells you a passage ranked low; the terms
tell you why, and the two are different findings:

- **`in no passage`** — the corpus has never seen this word. `does, dog,
  vacci` above is the whole story of that refusal: no amount of threshold
  tuning conjures a document about dogs. This is a coverage gap.
- **`too common to score`** — the corpus *has* the word, in so many passages
  that it distinguishes nothing, so it was suppressed. If a word you consider
  load-bearing shows up here, the corpus is repeating it everywhere.
- **`matched n/m`**, per candidate — which of the question's words that
  passage actually contained. A passage that matched one weak word and a
  passage that matched three strong ones can score similarly; only this line
  tells them apart, and it is what turns "the ranking looks wrong" into a
  claim you can check.

## 8. Serve the chat interface

```text
$ python3 -m cairn serve
cairn: serving the chat interface on http://127.0.0.1:8765/  (ctrl-c to stop)
cairn: 40 passages, 10 documents, languages ar, en, es
```

Open that address. The page binds to this machine only, loads no external
resource of any kind, and declares a content security policy of
`default-src 'none'` so the browser enforces that rather than a README
claiming it.

What to try, and what should happen:

| Do this | Expect |
| --- | --- |
| Press <kbd>Tab</kbd> once from the top | The skip link appears and is focused |
| Press <kbd>Enter</kbd> on it | Focus lands in the question box |
| Keep pressing <kbd>Tab</kbd> | Transcript, language, question, send — then out of the page. No trap, and a visible focus ring at every stop |
| Type a question and press <kbd>Enter</kbd> | The answer is appended and announced politely; focus stays in the question box |
| Press <kbd>Shift</kbd>+<kbd>Enter</kbd> | A new line in the question box, as the hint under it says |
| Switch the language to العربية | The whole page mirrors — the send button moves to the other side — and the chrome is retranslated |
| Ask an English-only question in Arabic | An Arabic notice, then the English source marked `lang="en" dir="ltr"` so a screen reader reads it in an English voice |
| Turn off JavaScript and ask again | It still answers. The form posts to the server, which renders the page |
| Switch your system to dark mode | A dark presentation whose every colour pair passes AA |

The disclosure at the top of the page is permanent. There is no dismiss
control, because a disclosure you can dismiss is a disclosure most people
never see twice.

`tests/browser/` drives all of the above against real Chromium, along with
axe-core's WCAG 2.2 AA rule set in light, dark, and right-to-left. It needs
Node and a browser, and is deliberately not part of the dev path below.

## 9. Run the audit

The merge gate hands Cairn's own recorded answers to a separate project,
[Plumbline](https://github.com/ChelseaKR/plumbline), pinned to an exact commit
in [`plumbline.pin`](../plumbline.pin).

```text
$ python3 -m cairn record            # re-record the evidence from this engine
Recorded 27 items (21 answers, 6 refusals) in 3 languages [ar, en, es] -> plumbline/bundle
Bundle sha256: 167b79ba6076b8fb9796cd64e44be690a07af397941d26103c03b186a62297cc

$ ./plumbline-gate.sh                # resolve the pinned auditor and grade it
GATE: PASS — target cairn-demo, dataset 167b79ba6076, run ...
all 14 suites passed:
  ...
  passage_attribution    score 0.9412  floor 0.90  PASS  n=17  ci 0.730-0.990  mde 0.226  3 unverifiable
  ...

$ python3 audit_guard.py             # the check the gate cannot make on itself
GUARD: PASS — cairn-demo, run ..., against baseline ...
declared gaps: none — every implemented suite is enabled.
suites that could not check everything they were handed:
  passage_attribution: scored 17 of 20 eligible (no_distractor 3); ...
no suite moved against the committed baseline.
```

`passage_attribution` is the suite that can say **right document, wrong
paragraph**, and 0.9412 is one item failing it: `ck-022` is answered from the
housing document's deadline paragraph instead of the one with the amount in
it. Every other suite passes that item, correctly — the answer is grounded,
cited, and supported by the passage it points at. See
[DESIGN.md](../DESIGN.md#the-wrong-paragraph-gap-closed-upstream).

This one needs the network the first time, to fetch the pinned harness. It is
the only part of this page that does.

Two things worth trying:

```text
# 1. Break the evidence. The audit refuses to score rather than grading it.
$ sed -i '' 's/212/999/' plumbline/bundle/responses.jsonl
$ ./plumbline-gate.sh ; echo $?      # 3 — integrity refusal, nothing scored
$ python3 -m cairn record            # re-record honestly; the hash change is the trace

# 2. Break the pin. The gate fails; it does not skip.
$ sed 's#^repo = .*#repo = file:///nowhere.git#' plumbline.pin > /tmp/bad.pin
$ PLUMBLINE_PIN_FILE=/tmp/bad.pin ./plumbline-gate.sh ; echo $?    # 4
```

The second one is the property the whole interlock rests on. A skipped check
and a passed check are the same green tick on a pull request, so an
unresolvable auditor has to be red. `tests/test_interlock.py` runs that drill
on every test run, and so does CI.

`audit_guard.py` is the other half. The gate checks floors; the guard checks
the committed baseline, and fails on a score that no longer matches it **in
either direction** — a fall is a regression, a rise is an improvement nobody
recorded, and an unrecorded improvement leaves the bar low enough for a later
change to give the whole thing back unnoticed. It never edits the baseline
itself: both directions stop and hand a person the decision.

## 10. Grade the server instead of the recording

Everything above grades `plumbline/bundle`, which `cairn record` wrote by
calling the engine in process. A bundle is bytes on disk and the server is
code that changes, so the same questions also get asked over HTTP:

```text
$ ./plumbline-live.sh
PLUMBLINE LIVE: serving cairn on 127.0.0.1:8766
recorded:  27 responses
verdict: PASS
LIVE: MATCH — http://127.0.0.1:8766/ask, recorded ...
  27 answers over HTTP, byte-identical to the recorded evidence the gate grades.
  the audited interface snapshot is the page being served.
```

It starts the server, has the pinned harness's HTTP recorder seal what comes
back, audits that bundle against the same floors, and then compares it to the
committed evidence. Run `./plumbline-gate.sh` first: the live check
deliberately cannot fetch the harness, only borrow the checkout the gate
verified.

This is an addition, not the gate. The gate stays offline and deterministic;
`plumbline.pin` does not name the live config, and a run that needs a server
to come up is not a run that can decide a merge.

## The dev path

```console
$ python3 -m unittest discover -s tests
$ ruff check .
```

No third-party dependency is required to run the tests, and no auditor: the
core path works with the harness completely unreachable, which CI proves on
every run. `ruff` is the only development extra, and the demo path does not
need it.
