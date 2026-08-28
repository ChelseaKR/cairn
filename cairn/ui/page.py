"""The served page, built as a string.

No template engine: the runtime is standard library only, and a page this size
is more legible as functions that return markup than as a template with logic
hidden in it.

Two properties are load-bearing and easy to lose, so they are stated here and
tested in ``tests/test_ui.py``:

**The page is complete before JavaScript runs.** The form posts to the same
endpoint the script uses, and a POST without JavaScript comes back as a fully
rendered page with the answer in it. The script upgrades that into a live
transcript; it is not what makes the page work. (Without the script each answer
replaces the transcript rather than accumulating, which is the one behavior
that genuinely needs client state.)

**Every element that carries text in a language says which language, and
which direction.** Not only the document: an English source quoted inside an
Arabic session is marked ``lang="en" dir="ltr"`` on its own element, and the
Latin passage id inside it is wrapped in ``<bdi>``. A screen reader switches
voice on the first; a browser stops reordering punctuation on the second.
"""

from __future__ import annotations

import json
import re
from html import escape

from cairn.answer import Answer
from cairn.engine import AskResult
from cairn.language import LANGUAGES, direction_of
from cairn.messages import catalogue_for
from cairn.messages import text as message

# The selector's options: every interface language, in the order
# `cairn.language.LANGUAGES` declares them.
#
# Derived rather than listed. It was `("en", "es", "ar")`, written by hand
# before French existed and never revisited, and the cost was not a missing
# dropdown entry. `cairn/server.py`'s `_resolve_lang` reads this tuple to
# decide whether a requested language is real, and falls back to the
# configured default when it is not -- silently, which is right for a
# garbage query string and wrong for a language the interface genuinely
# speaks. So a French speaker asking the served page or the JSON API in
# French was answered in English, with a cross-language notice explaining
# that the French source was "in another language". Every other layer knew
# better: `LANGUAGES` had the entry, `messages.py` had the full catalogue,
# `available_languages()` offered it, and `cairn ask --lang fr` worked.
#
# Found by tests/test_live.py the moment French corpus content existed for
# the served engine to get wrong, which is three years of nobody looking
# compressed into one afternoon. `tests/test_ui.py` now holds this tuple to
# `LANGUAGES` so it cannot drift again.
SELECTABLE = tuple(LANGUAGES)

# The element the script reads its own voice out of, before it has fetched
# anything.
STRINGS_ELEMENT_ID = "ui-strings"


def _attrs(lang: str) -> str:
    return f'lang="{escape(lang)}" dir="{direction_of(lang)}"'


# A Markdown ATX heading line, and the marker to take off the front of it.
# These two patterns are the whole rule, and ``cairn/ui/static/app.js`` spells
# them character for character: the script rebuilds this markup client-side,
# and a renderer that disagreed with itself about what a heading is would put
# a literal ``##`` on one of the two paths and not the other.
# ``tests/test_ui.py`` fails if the two files stop matching.
ATX_LINE = re.compile(r"^\s*#{1,6}(?:\s|$)")
ATX_MARKER = re.compile(r"^\s*#+\s*")


def _quoted_block(body: str) -> str:
    """Corpus text, rendered.

    Markdown ATX markers are dropped and the heading line is emphasized
    instead. That removes markup, never words: every word of the passage
    survives into the page, which is what "the answer is the source, verbatim"
    has to mean on screen. What does not survive is the marker itself and the
    whitespace around it — including the indentation in front of it, which the
    older rule kept, and which made an indented heading render its own ``##``
    on the page while the script next door dropped it.

    A line that is only markers has nothing to emphasize, so it is left alone
    and printed as it stands.

    ``#`` only opens a heading when a space or the end of the line follows it,
    and up to six of them. The rule used to be "the line starts with ``#``",
    which is not Markdown and cost a character of somebody's benefit
    information: a passage reading ``#1 priority is rent`` rendered as
    **1 priority is rent**, and ``#4 bus route runs hourly`` lost its route
    number. Both tests that covered this built their expected value by running
    ``ATX_MARKER`` over the input, so the bug was the specification and could
    not fail.

    Lines are split on ``\\n`` and nothing else, to match the script. Python's
    ``splitlines`` also breaks on U+2028, form feed, vertical tab and U+0085,
    and the join then wrote ``\\n`` back in their place — so a passage from a
    Word or PDF extraction rendered on the server with characters the cited
    source does not contain, while the same answer rendered client-side kept
    them. The parity test compared the two regexes and not the splitting rule,
    which is the other half of the algorithm.
    """
    out = []
    for line in body.split("\n"):
        stripped = ATX_MARKER.sub("", line)
        if ATX_LINE.match(line) and stripped:
            out.append(f"<strong>{escape(stripped)}</strong>")
        else:
            out.append(escape(line))
    return "\n".join(out)


def _answer_blocks(answer: Answer) -> str:
    """The answer body, one block per cited passage.

    Each block declares the language of the passage it quotes, not the
    language of the conversation. Marking an English quote as Arabic because
    the session is Arabic is the exact bug this shape exists to prevent.
    """
    if not answer.sources:
        return (
            f'    <div class="answer" {_attrs(answer.lang)}>'
            f"{_quoted_block(answer.text)}</div>"
        )
    return "\n".join(
        f'    <div class="answer" {_attrs(source.lang)}>{_quoted_block(source.text)}</div>'
        for source in answer.sources
    )


def _sources(answer: Answer, lang: str) -> str:
    if not answer.sources:
        return ""
    items = []
    for source in answer.sources:
        items.append(
            f"      <li {_attrs(source.lang)}>{escape(source.title)} "
            f"(<bdi>{escape(source.source_id)}</bdi>)</li>"
        )
    heading = escape(message("sources_heading", lang))
    return (
        f'    <h4 class="sources-heading">{heading}</h4>\n'
        f'    <ol class="sources">\n' + "\n".join(items) + "\n    </ol>"
    )


def _copy_export(answer: Answer, lang: str) -> str:
    """A read-only, always-visible way to get the answer out of the page
    with its citations intact — no JavaScript required, no live region
    touched, no `id` minted (a `<label for>` would collide across repeated
    transcript turns; `aria-label` on the control needs none).

    `<details>`/`<summary>` is a native disclosure widget: keyboard-operable
    and announced correctly with no ARIA authored for it, so the transcript
    stays compact by default without adding an interaction the markup layer
    has to get right on its own.

    Only for a grounded answer. A refusal has no sources to preserve, and
    `Answer.cited_text` for one is just `Answer.text` again (see
    `cairn/answer.py`) — nothing this control would add over the refusal
    text already on the page.
    """
    if not answer.sources:
        return ""
    label = escape(message("copy_answer_summary", lang))
    body = escape(answer.cited_text)
    return f"""    <details class="copy-answer">
      <summary>{label}</summary>
      <textarea readonly rows="4" {_attrs(answer.lang)} aria-label="{label}">{body}</textarea>
    </details>"""


def _followup_form(question: str, lang: str) -> str:
    """The opt-in "request a follow-up" action on a refusal, only.

    A native `<details>`/`<summary>` disclosure again — see `_copy_export`
    for why that widget rather than an always-open form: closed by default,
    keyboard-operable, and announced correctly with no ARIA authored for it.

    Both the contact field and the checkbox use an *implicit* label — the
    whole `<label>` wraps the control, so there is no `for`/`id` pair to
    collide the way `_copy_export`'s control would have across repeated
    transcript turns (see that function's docstring). A refusal can recur
    more than once in one session, and each occurrence gets its own,
    independently addressable form this way with zero ids minted anywhere.

    The question is carried in a hidden field so `/follow-up` can be handed
    it — the same trust boundary as the `question` field `/ask` already
    reads from this same origin — but whether it is ever *stored* is a
    decision `cairn/server.py` makes strictly from the `include_question`
    checkbox on this specific submission, never from this field's mere
    presence. See `cairn/followup.py`'s module docstring.
    """
    explanation = escape(message("followup_explanation", lang))
    contact_label = escape(message("followup_contact_label", lang))
    include_label = escape(message("followup_include_question_label", lang))
    submit_label = escape(message("followup_submit_button", lang))
    return f"""    <details class="followup">
      <summary>{escape(message("followup_heading", lang))}</summary>
      <p>{explanation}</p>
      <form method="post" action="/follow-up">
        <input type="hidden" name="lang" value="{escape(lang)}">
        <input type="hidden" name="question" value="{escape(question)}">
        <label class="field">
          {contact_label}
          <input type="text" name="contact" required>
        </label>
        <label class="field checkbox-field">
          <input type="checkbox" name="include_question" value="yes">
          {include_label}
        </label>
        <button type="submit" class="send">{submit_label}</button>
      </form>
    </details>"""


def turn_markup(
    question: str, result: AskResult, lang: str, *, followup_enabled: bool = False
) -> str:
    """One question and its answer, as the transcript holds them.

    The client script builds the identical structure, so the announced
    transcript and the no-JavaScript page are the same page.

    `followup_enabled` is off by default — the only path this function
    reaches without an operator running `cairn serve --followup-store`. On,
    it adds `_followup_form` to a refusal turn only: a grounded answer
    already names sources an asker can act on, and the whole point of the
    form is a channel for the case where nothing here answered.
    """
    answer = result.answer
    label = message(
        "assistant_said" if answer.kind == "grounded" else "assistant_refused", lang
    )
    notice = (
        f'    <p class="notice" {_attrs(answer.lang)}>{escape(answer.notice)}</p>\n'
        if answer.notice
        else ""
    )
    followup = (
        f"\n{_followup_form(question, lang)}"
        if followup_enabled and answer.kind == "refusal"
        else ""
    )
    return f"""  <li class="turn turn-asked">
    <h3 class="turn-label">{escape(message("you_said", lang))}</h3>
    <p class="asked" {_attrs(lang)}>{escape(question)}</p>
  </li>
  <li class="turn turn-answered turn-{answer.kind}">
    <h3 class="turn-label">{escape(label)}</h3>
{notice}{_answer_blocks(answer)}
{_sources(answer, lang)}
{_copy_export(answer, lang)}{followup}
  </li>"""


def _language_options(lang: str) -> str:
    options = []
    for code in SELECTABLE:
        language = LANGUAGES[code]
        selected = " selected" if code == lang else ""
        options.append(
            f'          <option value="{code}" lang="{code}" '
            f'dir="{language.direction}"{selected}>{escape(language.endonym)}</option>'
        )
    return "\n".join(options)


def _disclosure(lang: str) -> str:
    points = "\n".join(
        f"        <li>{escape(message(key, lang))}</li>"
        for key in (
            "disclosure_ai",
            "disclosure_sources",
            "disclosure_limits",
            "disclosure_synthetic",
        )
    )
    return f"""      <section class="disclosure" aria-labelledby="disclosure-heading">
        <h2 id="disclosure-heading">{escape(message("disclosure_heading", lang))}</h2>
        <ul>
{points}
        </ul>
      </section>"""


def _embedded_strings(lang: str) -> str:
    """This page's own language, served with the page.

    The announcements are the interface's voice: "the answer is ready, with
    two sources", "your question could not be sent". They were fetched from
    ``/strings.json`` alongside every other language, which meant that until
    that response arrived the script had nothing to say — and said it. An
    empty live region announces nothing at all, so for a window after every
    page load the interface was mute exactly where it promises to speak, and
    permanently mute if the fetch failed. Serving the current language *in*
    the page removes the window: the strings are there before the script runs.
    ``/strings.json`` is still fetched, for the one thing it is genuinely
    needed for, which is switching to a language this page was not rendered
    in.

    Not executable script, so the `default-src 'none'` policy is untouched;
    ``<`` is escaped so no catalogue entry could ever close the element early.
    """
    payload = json.dumps(catalogue_for(lang), ensure_ascii=False, sort_keys=True)
    return payload.replace("<", "\\u003c")


def render_page(
    lang: str, *, turns: str = "", status: str = "", followup_notice: str = ""
) -> str:
    """The whole document. ``turns`` is pre-rendered transcript markup.

    ``followup_notice``, when given, is a plain visible confirmation shown
    at the top of the page — the response to a `/follow-up` submission,
    which (like `/ask` without JavaScript) is a full page reload, not a
    live-region update. It is deliberately *not* rendered into the existing
    ``#status`` live region: that region's content is only ever announced on
    a change after the page has already loaded, which a fresh page load is
    not, so relying on it here would give some readers no confirmation at
    all. A plain, visible paragraph in normal document order is read by
    everyone regardless of how their browser or assistive technology
    happens to handle a live region present at load time.
    """
    direction = direction_of(lang)
    empty = escape(message("transcript_empty", lang))
    body = turns or f'  <li class="turn turn-empty"><p>{empty}</p></li>'
    notice_block = (
        f'\n      <p class="page-notice" role="status">{escape(followup_notice)}</p>'
        if followup_notice
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="{escape(lang)}" dir="{direction}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(message("page_title", lang))}</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <a class="skip-link" href="#question">{escape(message("skip_link", lang))}</a>
  <div class="page">
    <header>
      <h1>{escape(message("heading_main", lang))}</h1>
    </header>
    <main>{notice_block}
{_disclosure(lang)}

      <h2 id="transcript-heading">{escape(message("transcript_heading", lang))}</h2>
      <div id="transcript" class="transcript" role="log" aria-live="polite"
           aria-labelledby="transcript-heading" tabindex="0">
        <ol id="turns" class="turns">
{body}
        </ol>
      </div>

      <p id="status" role="status" class="visually-hidden">{escape(status)}</p>
      <div id="errors" role="alert" class="errors"></div>

      <form id="ask" method="post" action="/ask" aria-labelledby="form-heading">
        <h2 id="form-heading">{escape(message("form_heading", lang))}</h2>
        <div class="field">
          <label for="lang">{escape(message("language_label", lang))}</label>
          <select id="lang" name="lang">
{_language_options(lang)}
          </select>
        </div>
        <div class="field">
          <label for="question">{escape(message("input_label", lang))}</label>
          <textarea id="question" name="question" rows="3"
                    aria-describedby="question-hint"></textarea>
          <p id="question-hint" class="hint">{escape(message("input_hint", lang))}</p>
        </div>
        <button type="submit" class="send">{escape(message("send_button", lang))}</button>
      </form>
    </main>
  </div>
  <script type="application/json" id="{STRINGS_ELEMENT_ID}">{_embedded_strings(lang)}</script>
  <script src="/app.js"></script>
</body>
</html>
"""
