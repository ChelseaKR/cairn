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

from html import escape

from cairn.answer import Answer
from cairn.engine import AskResult
from cairn.language import LANGUAGES, direction_of
from cairn.messages import text as message

# Interface languages, in a stable order, for the selector.
SELECTABLE = ("en", "es", "ar")


def _attrs(lang: str) -> str:
    return f'lang="{escape(lang)}" dir="{direction_of(lang)}"'


def _quoted_block(body: str) -> str:
    """Corpus text, rendered.

    Markdown ATX markers are dropped and the heading line is emphasized
    instead. That removes markup, never words: every character of the passage
    that is not a leading ``#`` marker survives into the page, which is what
    "the answer is the source, verbatim" has to mean on screen.
    """
    out = []
    for line in body.splitlines():
        stripped = line.lstrip("#").strip()
        if line.lstrip().startswith("#") and stripped:
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


def turn_markup(question: str, result: AskResult, lang: str) -> str:
    """One question and its answer, as the transcript holds them.

    The client script builds the identical structure, so the announced
    transcript and the no-JavaScript page are the same page.
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
    return f"""  <li class="turn turn-asked">
    <h3 class="turn-label">{escape(message("you_said", lang))}</h3>
    <p class="asked" {_attrs(lang)}>{escape(question)}</p>
  </li>
  <li class="turn turn-answered turn-{answer.kind}">
    <h3 class="turn-label">{escape(label)}</h3>
{notice}{_answer_blocks(answer)}
{_sources(answer, lang)}
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


def render_page(lang: str, *, turns: str = "", status: str = "") -> str:
    """The whole document. ``turns`` is pre-rendered transcript markup."""
    direction = direction_of(lang)
    empty = escape(message("transcript_empty", lang))
    body = turns or f'  <li class="turn turn-empty"><p>{empty}</p></li>'
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
    <main>
{_disclosure(lang)}

      <h2 id="transcript-heading">{escape(message("transcript_heading", lang))}</h2>
      <ol id="transcript" class="transcript" role="log" aria-live="polite"
          aria-labelledby="transcript-heading" tabindex="0">
{body}
      </ol>

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
  <script src="/app.js"></script>
</body>
</html>
"""
