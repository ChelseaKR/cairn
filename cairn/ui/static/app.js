/* Cairn chat interface — progressive enhancement only.
 *
 * The page already works without this file: the form posts to /ask and the
 * server returns a rendered page. What this adds is the thing a page reload
 * cannot do — an accumulating transcript that is announced politely while
 * focus stays where the reader put it.
 *
 * Three rules are enforced structurally rather than by discipline:
 *
 * 1. Nothing here ever calls focus() on new content. New answers are appended
 *    to a polite live region and announced; the caret stays in the textarea.
 * 2. announceError() is the only function that writes to the assertive
 *    region, and it is the only writer of #errors anywhere in the codebase.
 *    Everything else goes to the polite #status. An assertive region that
 *    also carries routine progress is an assertive region nobody can use.
 * 3. Every element that carries text sets lang and dir from the payload, so
 *    an English source quoted in an Arabic session is still announced in an
 *    English voice and laid out left to right inside a right-to-left page.
 */

(function () {
  "use strict";

  var form = document.getElementById("ask");
  var transcript = document.getElementById("transcript");
  var turns = document.getElementById("turns");
  var statusLine = document.getElementById("status");
  var errorLine = document.getElementById("errors");
  var input = document.getElementById("question");
  var langSelect = document.getElementById("lang");
  var sendButton = form.querySelector("button[type=submit]");

  /* The interface's own voice. The page it was loaded from carries the
     language it was rendered in, so every announcement works from the first
     keystroke and keeps working even if the fetch below never lands.
     /strings.json adds the *other* languages, which is all the selector
     needs. This used to be one fetch for everything, and until it resolved
     the script announced the empty string into a live region — silence, in
     the two places the interface promises to speak. */
  var strings = (function () {
    var block = document.getElementById("ui-strings");
    var table = {};
    if (!block) return table;
    try {
      table[document.documentElement.lang] = JSON.parse(block.textContent);
    } catch (error) {
      /* Leave it empty; the page still posts and the server still renders. */
    }
    return table;
  })();

  function announce(text) {
    statusLine.textContent = text;
  }

  /* The only writer of the assertive region. */
  function announceError(text) {
    errorLine.textContent = text;
  }

  function clearError() {
    errorLine.textContent = "";
  }

  function say(key, fields) {
    var table = strings[langSelect.value] || {};
    var template = table[key];
    if (!template) return "";
    return template.replace(/\{(\w+)\}/g, function (whole, name) {
      return fields && name in fields ? fields[name] : whole;
    });
  }

  function element(tag, className, text, lang, dir) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    if (lang) node.lang = lang;
    if (dir) node.dir = dir;
    return node;
  }

  /* Corpus text, rendered: markdown heading markers become emphasis. Words are
     never altered — see cairn/ui/page.py, which produces identical markup. */
  function quoted(container, body) {
    body.split("\n").forEach(function (line, position) {
      if (position > 0) container.appendChild(document.createTextNode("\n"));
      var trimmed = line.replace(/^\s*#+\s*/, "");
      if (/^\s*#/.test(line) && trimmed) {
        container.appendChild(element("strong", null, trimmed));
      } else {
        container.appendChild(document.createTextNode(line));
      }
    });
  }

  function addTurn(question, payload, uiLang) {
    var empty = turns.querySelector(".turn-empty");
    if (empty) empty.remove();

    var asked = element("li", "turn turn-asked");
    asked.appendChild(element("h3", "turn-label", say("you_said")));
    asked.appendChild(
      element("p", "asked", question, uiLang, dirOf(uiLang))
    );
    turns.appendChild(asked);

    var grounded = payload.kind === "grounded";
    var answered = element("li", "turn turn-answered turn-" + payload.kind);
    answered.appendChild(
      element(
        "h3",
        "turn-label",
        say(grounded ? "assistant_said" : "assistant_refused")
      )
    );
    if (payload.notice) {
      answered.appendChild(
        element("p", "notice", payload.notice, payload.lang, payload.dir)
      );
    }
    /* One block per cited passage, each declaring the language of the passage
       it quotes rather than the language of the conversation. A refusal has no
       sources, and speaks in the conversation's language. */
    if (payload.sources.length) {
      payload.sources.forEach(function (source) {
        var body = element("div", "answer", null, source.lang, source.dir);
        quoted(body, source.text);
        answered.appendChild(body);
      });
    } else {
      var refusal = element("div", "answer", null, payload.lang, payload.dir);
      quoted(refusal, payload.text);
      answered.appendChild(refusal);
    }

    if (payload.sources.length) {
      answered.appendChild(
        element("h4", "sources-heading", say("sources_heading"))
      );
      var list = element("ol", "sources");
      payload.sources.forEach(function (source) {
        var item = element("li", null, null, source.lang, source.dir);
        item.appendChild(document.createTextNode(source.title + " ("));
        var id = document.createElement("bdi");
        id.textContent = source.id;
        item.appendChild(id);
        item.appendChild(document.createTextNode(")"));
        list.appendChild(item);
      });
      answered.appendChild(list);
    }
    turns.appendChild(answered);
    transcript.scrollTop = transcript.scrollHeight;

    announce(
      grounded
        ? say("status_answered", { count: payload.sources.length })
        : say("status_refused")
    );
  }

  function dirOf(lang) {
    var option = langSelect.querySelector('option[value="' + lang + '"]');
    return option ? option.dir : document.documentElement.dir;
  }

  /* Retranslate the page chrome in place. Direction is applied to the document
     element, so the whole layout mirrors rather than the text merely changing. */
  function applyLanguage(lang) {
    var table = strings[lang];
    if (!table) return;
    document.documentElement.lang = lang;
    document.documentElement.dir = dirOf(lang);
    document.title = table.page_title;
    setText(".skip-link", table.skip_link);
    setText("h1", table.heading_main);
    setText("#disclosure-heading", table.disclosure_heading);
    var points = document.querySelectorAll(".disclosure li");
    [
      table.disclosure_ai,
      table.disclosure_sources,
      table.disclosure_limits,
      table.disclosure_synthetic
    ].forEach(function (value, position) {
      if (points[position]) points[position].textContent = value;
    });
    setText("#transcript-heading", table.transcript_heading);
    setText(".turn-empty p", table.transcript_empty);
    setText("#form-heading", table.form_heading);
    setText('label[for="lang"]', table.language_label);
    setText('label[for="question"]', table.input_label);
    setText("#question-hint", table.input_hint);
    setText("button[type=submit]", table.send_button);
    var url = new URL(window.location.href);
    url.searchParams.set("lang", lang);
    window.history.replaceState(null, "", url);
  }

  function setText(selector, value) {
    var node = document.querySelector(selector);
    if (node && value) node.textContent = value;
  }

  function submit(event) {
    event.preventDefault();
    clearError();
    var question = input.value.trim();
    var lang = langSelect.value;
    if (!question) {
      announceError(say("error_empty_question"));
      return;
    }
    sendButton.disabled = true;
    announce(say("status_working"));
    fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ question: question, lang: lang })
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        addTurn(question, payload, lang);
        input.value = "";
      })
      .catch(function () {
        /* Nothing was answered, so nothing goes in the transcript. The
           assertive channel exists for exactly this. */
        announce("");
        announceError(say("error_request_failed"));
      })
      .then(function () {
        sendButton.disabled = false;
      });
  }

  form.addEventListener("submit", submit);

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit ? form.requestSubmit() : submit(new Event("submit"));
    }
  });

  langSelect.addEventListener("change", function () {
    applyLanguage(langSelect.value);
  });

  fetch("/strings.json", { headers: { Accept: "application/json" } })
    .then(function (response) {
      return response.json();
    })
    .then(function (payload) {
      Object.keys(payload).forEach(function (lang) {
        strings[lang] = payload[lang];
      });
      document.documentElement.setAttribute("data-strings", "ready");
    })
    .catch(function () {
      /* The page keeps working, and so does its voice: this page's own
         language came with the page. Only in-place switching to another one
         is lost, and saying so is better than a selector that silently does
         nothing. */
      langSelect.disabled = true;
      document.documentElement.setAttribute("data-strings", "unavailable");
    });
})();
