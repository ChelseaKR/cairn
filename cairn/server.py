"""The local web server behind ``cairn serve``.

``http.server`` from the standard library, because the demo path has to run on
a laptop with no network and no install step. It is a demonstration server: it
binds to localhost by default, keeps no state, stores nothing, and logs
nothing about the questions people ask. Two opt-in exceptions:
``--refusal-stats``, which stores an aggregate count per (language, reason)
pair on a refusal — never the question itself; see
``cairn/refusal_stats.py`` — and ``--followup-store``, an explicit "request
a follow-up" action on a refusal that stores an asker's own contact
information, and their question only if they separately choose to include
it; see ``cairn/followup.py``.

The content security policy is deliberately absolute — ``default-src 'none'``
with same-origin styles, scripts and fetches — so the offline claim is
enforced by the browser rather than asserted in a README. If a future change
adds a font from a CDN, the page breaks loudly instead of quietly requiring
the network. ``frame-ancestors`` is the one directive an operator can widen,
via ``--allow-embed``, and only to an explicit list of origins — see
``cairn/network.py`` and ``docs/embedding.md``.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cairn import __version__
from cairn.config import Config
from cairn.engine import EngineError, ask
from cairn.explain import refusal_reason
from cairn.followup import FollowupStore
from cairn.index import Index
from cairn.messages import CATALOGUE
from cairn.messages import text as message
from cairn.network import RateLimiter, check_token, cors_headers, frame_ancestors
from cairn.refusal_stats import RefusalCounter
from cairn.session import Session
from cairn.stream import sse_stream
from cairn.ui.page import SELECTABLE, render_page, turn_markup

STATIC = Path(__file__).resolve().parent / "ui" / "static"

CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

# A question longer than this is not a question. Bounds the request body so a
# demo server cannot be made to allocate without limit.
MAX_BODY_BYTES = 8 * 1024


def _resolve_lang(raw: str | None, default: str) -> str:
    return raw if raw in SELECTABLE else default


def build_handler(
    cfg: Config,
    index: Index,
    *,
    quiet: bool = False,
    auth_token: str = "",
    rate_limiter: RateLimiter | None = None,
    cors_origins: tuple[str, ...] = (),
    embed_origins: tuple[str, ...] = (),
    refusal_counter: RefusalCounter | None = None,
    followup_store: FollowupStore | None = None,
):
    """A request handler class bound to one configuration and index.

    `auth_token`, `rate_limiter`, `cors_origins`, `embed_origins`,
    `refusal_counter`, and `followup_store` are all off by default (empty
    token, `None` limiter, empty origin tuples, `None` counter, `None`
    store), which is the only path `cairn serve` reaches without an
    operator explicitly opting into networked deployment, cross-origin
    embedding, refusal analytics, or a real follow-up channel — see
    `cairn/network.py`, `cairn/refusal_stats.py`, `cairn/followup.py`,
    `docs/deployment.md`, and `docs/embedding.md`.
    """
    csp = (
        CSP
        if not embed_origins
        else (
            "default-src 'none'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; form-action 'self'; base-uri 'none'; "
            f"frame-ancestors {frame_ancestors(embed_origins)}"
        )
    )

    class CairnHandler(BaseHTTPRequestHandler):
        server_version = f"cairn/{__version__}"
        protocol_version = "HTTP/1.1"

        # --- plumbing ---------------------------------------------------

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            if not quiet:
                super().log_message(fmt, *args)

        def _gate(self) -> bool:
            """Auth then rate limit, in that order — an unauthenticated
            client should never learn it was also about to be rate
            limited. Writes the error response itself and returns `False`
            when the request should stop here; every route checks this
            first and returns immediately if it does.
            """
            if auth_token and not check_token(
                self.headers.get("Authorization"), auth_token
            ):
                body = json.dumps({"error": "unauthorized"}).encode("utf-8")
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return False
            if rate_limiter is not None and not rate_limiter.allow(self.client_address[0]):
                body = json.dumps({"error": "rate limit exceeded"}).encode("utf-8")
                self.send_response(429)
                self.send_header("Retry-After", "60")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return False
            return True

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for name, value in cors_headers(
                self.headers.get("Origin"), cors_origins
            ).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _html(self, markup: str, status: int = 200) -> None:
            self._send(status, markup.encode("utf-8"), "text/html; charset=utf-8")

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _static(self, name: str, content_type: str) -> None:
            path = STATIC / name
            if not path.is_file():
                self._html("<h1>404</h1>", status=404)
                return
            self._send(200, path.read_bytes(), content_type)

        def _read_body(self) -> bytes:
            """The request body, or nothing — and the connection closed if
            nothing.

            Two ways this went wrong, both from `protocol_version` being
            HTTP/1.1, which means a client may send a second request down the
            same socket.

            An oversized body was refused by returning `b""` and *not reading
            it*, so the unread bytes stayed in the stream and were parsed as
            the next request line. A client that pipelined a legitimate
            question behind an oversized one got back
            `501 Unsupported method ('question=aaaa...')` and never got its
            answer — a response that does not correspond to its request, which
            is the worst failure mode a request/response protocol has. The
            body is not drained (an attacker chooses its length); the
            connection is closed, which is what the standard says to do.

            And a non-numeric `Content-Length` raised `ValueError` straight
            out of here, killing the handler thread with a traceback on stderr
            and giving the client an empty response.

            The 501 also put a prefix of the question into the server's log,
            on a server whose module docstring says it logs nothing about the
            questions people ask. Closing the connection is what stops a
            question ever being read as a request line.
            """
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.close_connection = True
                return b""
            if length < 0 or length > MAX_BODY_BYTES:
                self.close_connection = True
                return b""
            return self.rfile.read(length)

        # --- routes -----------------------------------------------------

        def do_GET(self):  # noqa: N802 - stdlib naming
            if not self._gate():
                return
            route = urlparse(self.path)
            if route.path == "/":
                query = parse_qs(route.query)
                lang = _resolve_lang(
                    (query.get("lang") or [None])[0], cfg.default_lang
                )
                self._html(render_page(lang))
            elif route.path == "/app.css":
                self._static("app.css", "text/css; charset=utf-8")
            elif route.path == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
            elif route.path == "/strings.json":
                # Only the interface languages: the selector offers exactly
                # what the page can be retranslated into.
                self._json({code: CATALOGUE[code] for code in SELECTABLE})
            else:
                self._html("<h1>404</h1>", status=404)

        do_HEAD = do_GET

        def do_POST(self):  # noqa: N802 - stdlib naming
            if not self._gate():
                return
            route = urlparse(self.path).path
            if route == "/ask":
                self._handle_ask()
            elif route == "/follow-up" and followup_store is not None:
                self._handle_followup()
            else:
                self._html("<h1>404</h1>", status=404)

        def _handle_ask(self) -> None:
            raw = self._read_body()
            wants_json = "application/json" in (self.headers.get("Content-Type") or "")
            if wants_json:
                try:
                    submitted = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    self._json({"error": "malformed JSON body"}, status=400)
                    return
                question = str(submitted.get("question") or "")
                lang = _resolve_lang(submitted.get("lang"), cfg.default_lang)
            else:
                fields = parse_qs(raw.decode("utf-8"))
                question = (fields.get("question") or [""])[0]
                lang_values = fields.get("lang")
                lang = _resolve_lang(
                    lang_values[0] if lang_values else None, cfg.default_lang
                )

            question = question.strip()
            if not question:
                if wants_json:
                    self._json({"error": "empty question"}, status=400)
                else:
                    self._html(render_page(lang), status=400)
                return

            # Conversation state lives entirely with the client: a JSON
            # caller may attach its history (prior questions and the passage
            # ids they were answered from) and this request resolves the
            # follow-up against it. The server reconstructs a Session per
            # call and stores nothing — same stance as "no state, no
            # storage" above, applied to conversations. The no-JavaScript
            # form path stays single-turn by construction.
            session = None
            turn_meta = None
            if wants_json:
                history = submitted.get("history")
                if isinstance(history, dict):
                    try:
                        session = Session.from_payload(history)
                    except EngineError as exc:
                        self._json({"error": str(exc)}, status=400)
                        return

            try:
                if session is not None:
                    turn_result = session.ask(question, index, cfg, lang=lang)
                    result = turn_result.result
                    turn_meta = {
                        "resolved_with_context": turn_result.resolved_with_context,
                        "context_from_turns": list(turn_result.context_from_turns),
                        "context_terms": list(turn_result.context_terms),
                    }
                else:
                    result = ask(question, index, cfg, lang=lang)
            except EngineError as exc:
                # Reachable, and the comment here used to say it was not: it
                # read "lang is validated above", but `_resolve_lang` falls
                # back to `cfg.default_lang` and that was itself unvalidated,
                # so `[language] default = "fr"` served an HTML form client a
                # raw JSON error object. `Config` now refuses a default the
                # engine cannot answer in, which closes that door — and the
                # branch answers in the client's own content type rather than
                # assuming JSON, because a page that posts a form and gets
                # `{"error": ...}` is the no-JavaScript path breaking.
                if wants_json:
                    self._json({"error": str(exc)}, status=400)
                else:
                    self._html(render_page(cfg.default_lang), status=400)
                return

            if refusal_counter is not None and result.answer.kind == "refusal":
                # lang and a fixed reason code only — never the question.
                # See cairn/refusal_stats.py's module docstring for why that
                # boundary is structural rather than a promise about this
                # one call site.
                refusal_counter.record(lang, refusal_reason(result.answer.trace))

            offer_followup = followup_store is not None and result.answer.kind == "refusal"

            if wants_json and submitted.get("stream"):
                # Server-sent events over a close-delimited body: no
                # Content-Length is possible for a stream, and HTTP/1.1 makes
                # that legal exactly when `Connection: close` says the end of
                # the response *is* the end of the body. The frames are
                # cairn.stream's own, so a CLI --stream run and this endpoint
                # emit byte-identical sequences.
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                if self.command != "HEAD":
                    for frame in sse_stream(result.answer):
                        self.wfile.write(frame.encode("utf-8"))
                return

            if wants_json:
                payload = result.answer.to_payload()
                if result.tool is not None:
                    payload["tool"] = result.tool
                if turn_meta is not None:
                    payload["turn"] = turn_meta
                if offer_followup:
                    # A hint only, added here rather than in
                    # `Answer.to_payload()` (cairn/answer.py) — that method
                    # also backs `cairn record`'s evidence bundle and `cairn
                    # ask --json`, neither of which runs a server or has a
                    # follow-up store to offer. Adding a server-only key
                    # there would drift the bundle's own JSON shape for a
                    # feature the bundle has no opinion about.
                    payload = {**payload, "follow_up_available": True}
                self._json(payload)
            else:
                self._html(
                    render_page(
                        lang,
                        turns=turn_markup(
                            question, result, lang, followup_enabled=offer_followup
                        ),
                    )
                )

        def _handle_followup(self) -> None:
            """`POST /follow-up`: the opt-in request a refusal's disclosure
            form submits — see `cairn/ui/page.py`'s `_followup_form` and
            `cairn/followup.py`'s module docstring for the consent story.
            Only reachable at all when `followup_store` is configured;
            `do_POST` 404s this path otherwise, the same as any route this
            server does not have.
            """
            raw = self._read_body()
            wants_json = "application/json" in (self.headers.get("Content-Type") or "")
            if wants_json:
                try:
                    submitted = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    self._json({"error": "malformed JSON body"}, status=400)
                    return
                contact = str(submitted.get("contact") or "").strip()
                question = str(submitted.get("question") or "").strip()
                lang = _resolve_lang(submitted.get("lang"), cfg.default_lang)
                include_question = bool(submitted.get("include_question"))
            else:
                fields = parse_qs(raw.decode("utf-8"))
                contact = (fields.get("contact") or [""])[0].strip()
                question = (fields.get("question") or [""])[0].strip()
                lang_values = fields.get("lang")
                lang = _resolve_lang(
                    lang_values[0] if lang_values else None, cfg.default_lang
                )
                include_question = (fields.get("include_question") or [""])[0] == "yes"

            if not contact:
                if wants_json:
                    self._json({"error": "missing contact information"}, status=400)
                else:
                    self._html(
                        render_page(
                            lang,
                            followup_notice=message("error_missing_contact", lang),
                        ),
                        status=400,
                    )
                return

            assert followup_store is not None  # do_POST only reaches here if so
            followup_store.record(
                lang=lang,
                contact=contact,
                # Structural per-submission opt-in: the checkbox on *this*
                # request is the only thing that decides whether `question`
                # is ever written to the store. Unchecked, or absent
                # entirely (a JSON caller that never sent the field), and
                # None is stored — never an empty string standing in for
                # "the asker said no", which would be indistinguishable
                # from "the asker never got the choice."
                question=question if include_question else None,
            )
            if wants_json:
                self._json({"received": True})
            else:
                self._html(
                    render_page(
                        lang, followup_notice=message("followup_confirmation", lang)
                    )
                )

        def do_OPTIONS(self):  # noqa: N802 - stdlib naming
            """A CORS preflight response — deliberately not gated.

            A browser's preflight `OPTIONS` request never carries the
            `Authorization` header a real follow-up request would (that is
            what the preflight exists to negotiate *before* sending it), so
            checking `auth_token` here would 401 every preflight and the
            real request behind it would never be sent. It carries no
            request body and answers from `cors_origins` alone: a 404 for
            an origin that is not allowed, exactly like any other route this
            server does not recognize, and no route-specific logic beyond
            that CORS negotiation.
            """
            headers = cors_headers(self.headers.get("Origin"), cors_origins)
            if not headers:
                self._html("<h1>404</h1>", status=404)
                return
            self.send_response(204)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return CairnHandler


def serve(
    cfg: Config,
    index: Index,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
    auth_token: str = "",
    rate_limit_per_minute: int = 0,
    cors_origins: tuple[str, ...] = (),
    embed_origins: tuple[str, ...] = (),
    refusal_stats_path: Path | None = None,
    followup_store_path: Path | None = None,
):
    """Build a server. The caller decides when to start serving.

    `auth_token`, `rate_limit_per_minute`, `cors_origins`, `embed_origins`,
    `refusal_stats_path`, and `followup_store_path` are all off by default
    (see `cairn/network.py`, `cairn/refusal_stats.py`, and
    `cairn/followup.py`) — passing none of them reproduces exactly the
    server this project has always shipped.
    """
    handler = build_handler(
        cfg,
        index,
        quiet=quiet,
        auth_token=auth_token,
        rate_limiter=RateLimiter(rate_limit_per_minute) if rate_limit_per_minute > 0 else None,
        cors_origins=cors_origins,
        embed_origins=embed_origins,
        refusal_counter=RefusalCounter(refusal_stats_path) if refusal_stats_path else None,
        followup_store=FollowupStore(followup_store_path) if followup_store_path else None,
    )
    return ThreadingHTTPServer((host, port), handler)
