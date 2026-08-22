# Screen-reader test script

This is the honest gap named in `DESIGN.md` and `docs/compliance.md`: automated
checks (`tests/test_ui.py`, `tests/browser/a11y.mjs`) verify markup, semantics,
and rendered behavior in Chromium, but none of that is the same as a person
using a real screen reader. This script exists so that session takes an hour
with a checklist instead of a day of improvising.

It does not test anything the automated suite doesn't already assert. Every
task below has a corresponding automated check named in parentheses, so a
result that contradicts this script is either a regression the automation
missed or a difference between what Chromium/axe-core can verify and what a
real assistive-technology stack actually does — both are worth a bug report.

## Who this is for

Anyone with access to a screen reader and about an hour. No familiarity with
Cairn's code is required. You do need to be comfortable operating your screen
reader's normal browse mode and forms/focus mode, since this script exercises
both.

## Setup

Pick **one** combination to start with; repeat the whole script with a second
combination later if you have time. Coverage across combinations matters more
than depth on one.

| Screen reader | Browser | Platform |
|---|---|---|
| NVDA (free) | Firefox | Windows |
| VoiceOver (built in) | Safari | macOS |
| VoiceOver (built in) | Safari | iOS (optional, touch gestures differ — see note at the end) |
| JAWS | Chrome | Windows |

Start the server from a checkout of this repository:

```
$ python3 -m cairn serve
```

Open the printed URL (`http://127.0.0.1:8080/` by default) in your browser
with your screen reader running. Turn on speech output before you navigate
so you don't miss the page's first announcement.

Keep a copy of this script open on a second screen or printed — you'll be
switching between reading a task and operating the browser.

## Recording results

For each numbered task, write down:

- **Pass** — happened as described.
- **Fail** — describe what you heard/experienced instead.
- **Unclear** — you're not sure whether what happened was correct; describe
  it anyway and flag it for follow-up rather than guessing.

A single Fail on a task does not mean stop — finish the script and report
everything found together, so a fix can be checked against the whole list at
once rather than one issue at a time.

## Part 1 — First landing on the page

**1.1 Page load announcement.** Load the page fresh (or reload it). Before
you do anything else, what does your screen reader say? Expect it to reach a
heading fairly quickly — the page has a visible `<h1>` and skips no landmark
structure. *(Checked automatically by: axe-core WCAG 2.2 AA scan, empty-state,
`tests/browser/a11y.mjs`.)*

**1.2 First Tab stop is the skip link.** Press Tab once, from the very top of
the page (click the browser's address bar first, then Tab into the page, if
your reader doesn't already start you there). The very first thing that
receives focus should be a "skip to..." link, and it should become visible on
screen when focused (not just present silently). Press Enter. Focus should
land inside the question input, not at the top of the page again. *(Checked
automatically by: `checkSkipLink`, `checkKeyboardPath` in `a11y.mjs`.)*

**1.3 Landmarks and headings.** Switch to your screen reader's landmarks list
(NVDA: Insert+F7; VoiceOver: rotor, Web Landmarks; JAWS: Insert+F7 or the
Landmarks quick-nav key R). Confirm there is a main content region and that
the page's one `<h1>` reads as a real heading (not a styled `<div>`), not a
generic "region." *(Checked automatically by: `tests/test_ui.py`'s semantics
checks.)*

**1.4 Full read-through in browse mode.** Using your reader's "read from
current position" or "say all" command, listen to the entire page top to
bottom before interacting with anything. Note anything that sounds wrong out
of order, unlabeled, or announced twice. Pay particular attention to the
language switcher (should announce as a proper select/combo box with a
label) and any disclosure/notice text near the top of the page (should read
as ordinary text, not as a list of unlabeled items). *(Checked automatically
by: `tests/test_ui.py` markup checks; there is no automated equivalent of
"does the read-through sound coherent," which is exactly why this task
exists.)*

## Part 2 — Asking a question

**2.1 Locate and label of the question field.** Tab or use quick-nav to reach
the question input directly (not via the skip link this time). Your reader
should announce it with a clear, accurate label — not "edit text" alone, not
a placeholder standing in for a label. *(Checked automatically by:
`tests/test_ui.py`.)*

**2.2 Ask the demo question.** Type exactly:

```
How much is the monthly grocery allowance for one person?
```

Press Enter (or activate the Send button — try both across your two passes if
you have time). Listen closely to what happens next. Expect:

- Your reader announces new text appearing on the page — the answer — without
  you needing to move focus yourself.
- Focus **stays on the question field**. It should not jump to the answer,
  to the top of the page, or anywhere else. You should be able to keep
  typing a follow-up immediately.
- The announced answer should include the figure **$212** somewhere.
- After the answer, your reader should also make you aware of at least one
  source citation (a document title), not just the prose answer with no
  attribution.

*(Checked automatically by: `checkAnnouncement` in `a11y.mjs` — this is the
single most important task in this script, since "never steal focus, but
still announce" is a real screen-reader behavior that a sighted visual check
cannot confirm on its own.)*

**2.3 Ask a second question.** With focus still on the question field, clear
it and ask a different question (anything — even a question Cairn will
refuse, like "what's the weather today"). Confirm your reader announces the
new answer or refusal. Then navigate back up through the page's history in
browse mode and confirm your **first** question and its answer are still
there and still readable — the page accumulates a transcript rather than
replacing it. *(Checked automatically by: `checkAnnouncement`'s
transcript-accumulation assertion.)*

**2.4 Ask an empty question.** Clear the question field completely and press
Enter (or activate Send) with nothing typed. Nothing should be sent to the
server — confirm no new "asking..." or answer announcement happens — and your
reader should instead announce an error message. This error should sound
different in kind from the polite answer announcements in 2.2/2.3: expect it
to interrupt more assertively (a screen reader typically speaks an "alert"
over other speech, rather than waiting its turn). *(Checked automatically by:
`checkErrorChannel` in `a11y.mjs`, including a network-level assertion that
zero requests are sent for a whitespace-only question — the automated check
proves the network behavior; this task proves the announcement is actually
distinguishable by ear.)*

## Part 3 — Language switching

**3.1 Switch to Arabic.** Find the language selector (a standard select/combo
box near the top of the page). Change it to Arabic. Your reader should
announce the change. Confirm:

- The page's overall reading direction changes — right-to-left. Your screen
  reader may announce this, or you may notice it from how browse-mode
  navigation now moves through the page.
- The heading and surrounding page text are now spoken in Arabic, in your
  reader's Arabic voice/pronunciation if it has one configured (or spelled
  out phonetically if not — either is fine; what matters is that it's not
  silently skipped or read as the wrong language).

*(Checked automatically by: `checkRightToLeft` in `a11y.mjs`, plus a full
axe-core WCAG scan of the Arabic RTL state in both light and dark color
schemes.)*

**3.2 Ask a question in the Arabic session, in English.** With the language
still set to Arabic, ask the same demo question from 2.2, typed in English.
The answer will quote source text that is itself written in English. Listen
for whether your reader's pronunciation/voice actually shifts for that quoted
span, or at minimum whether it doesn't try to force Arabic pronunciation onto
English words — the underlying markup tags that one quoted span with its own
English language attribute distinct from the surrounding Arabic page.
*(Checked automatically by: `checkRightToLeft`'s language-tagging assertion —
this is a case where automation checks the markup exists; only a real reader
tells you whether it's audible.)*

**3.3 Switch back to English** before continuing, so the rest of this script
matches the task descriptions.

## Part 4 — Keyboard-only operation

Do this part without touching a mouse or trackpad at all — unplug it or set
it aside if that helps you keep honest.

**4.1 Full forward tab order.** Starting from the top of the page, Tab
through every interactive element in order, narrating out loud (or writing
down) what each one is. Expect, in order: the skip link, the language
selector, the question field, the Send button. Confirm nothing is skipped,
nothing receives focus twice in a row unexpectedly, and — importantly —
**every element that receives focus is visibly highlighted on screen** if you
have someone sighted checking alongside you, or that you can otherwise
confirm focus is visually tracked (this matters for people who use a screen
reader alongside low vision, not just people who can't see the screen at
all). *(Checked automatically by: `checkKeyboardPath` and
`checkFocusVisibility` in `a11y.mjs`, in both light and dark color schemes.)*

**4.2 Shift+Tab backward from the question field.** With focus on the
question field, press Shift+Tab once. Focus should land back on the language
selector — the reverse of the forward order, not skipping anywhere or
wrapping to the end of the page. *(Checked automatically by:
`checkKeyboardPath`.)*

**4.3 Keep tabbing to the end.** Continue tabbing forward past the Send
button. Eventually focus should cycle back to the very top of the document
(effectively back to the browser chrome or the start of the page) rather than
getting stuck on an element or looping on something in the middle
indefinitely. *(Checked automatically by: `checkKeyboardPath`'s
last-stop-cycles assertion.)*

## Part 5 — Target size and touch (if testing on a touchscreen device)

Skip this part entirely if you're on a desktop/laptop with no touchscreen.

**5.1 Tap targets.** Using VoiceOver on iOS (or TalkBack on Android, if you
have access to one), swipe through the language selector, question field,
and Send button. Each should be comfortably tappable without needing
precision — none should feel like a small target you have to aim carefully
for. *(Checked automatically by: `checkTargetSizes` in `a11y.mjs`, which
verifies each is at least 24×24 CSS pixels — a machine-checkable proxy for
"comfortable to tap" that this task double-checks by feel.)*

## Wrap-up

Once you've completed all five parts, note:

- Which screen reader / browser / platform combination you used.
- Every task marked Fail or Unclear, with what you actually heard/experienced.
- Anything that felt wrong but doesn't map to a specific task above — write
  it down anyway. The automated suite has 63 pinned assertions; it does not
  have all of them, and "this was confusing" from a real session is data the
  automation structurally cannot produce.

Report results by opening an issue, or send them directly if you were asked
to run this script as part of a specific review — either way, include the
combination you tested and the task numbers, so a second pass can pick up
where you left off instead of starting over.
