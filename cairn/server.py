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
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from cairn import __version__
from cairn.answer import Answer
from cairn.config import Config
from cairn.engine import AskResult, EngineError, ask
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


def _json_object(raw: bytes) -> dict[str, Any]:
    """The request body as a JSON *object*, or `ValueError`.

    Parsing is only half of reading a body. `json.loads(b"[1,2]")` succeeds,
    and the route then called `.get` on a list -- killing the handler thread
    with an `AttributeError` on stderr and giving the client no status and no
    body, which a caller cannot tell apart from a network fault. Every other
    bad request on these routes gets a 400 in the client's own content type.

    So "parsed to something that is not an object" is raised as the same
    `ValueError` that "did not parse" already raises, and lands on the same
    400: a caller who sent `[1,2]` has made the same class of mistake as one
    who sent `{`. `bytes.decode` raises `UnicodeDecodeError`, itself a
    `ValueError`, so an undecodable body arrives at the same place.

    The mirror of `_read_body`'s own docstring, one door along: there, a
    header that would not parse; here, a body that parsed to the wrong thing.
    """
    parsed = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("the request body must be a JSON object")
    return parsed


class CairnHandler(BaseHTTPRequestHandler):
    """The handler proper, with what it serves bound as class attributes.

    Bound rather than passed in, because there is nowhere to pass them:
    ``socketserver`` constructs one handler per request with the socket and
    the address and nothing else, so a ``Config`` cannot arrive through
    ``__init__``. :func:`build_handler` subclasses this and fills the
    attributes below in for one server; instantiating this class directly
    leaves them unset, and every method here would raise on the first one it
    reads.

    Each attribute was a closure variable of ``build_handler`` until
    2026-08-27, which is why they are declared in one block: a reader could
    otherwise only learn what a handler is configured with by reading the
    factory's signature, and the methods that read them were nested inside
    that factory, where every branch in every route counted toward one
    complexity number (56 of it, issue #42).
    """

    server_version = f"cairn/{__version__}"
    protocol_version = "HTTP/1.1"

    _cfg: ClassVar[Config]
    _index: ClassVar[Index]
    _quiet: ClassVar[bool]
    # The assembled policy, not the origins it was assembled from: the
    # ``frame-ancestors`` widening is decided once, in the factory.
    _csp: ClassVar[str]
    _auth_token: ClassVar[str]
    _rate_limiter: ClassVar[RateLimiter | None]
    _cors_origins: ClassVar[tuple[str, ...]]
    _refusal_counter: ClassVar[RefusalCounter | None]
    _followup_store: ClassVar[FollowupStore | None]

    # --- plumbing -------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        if not self._quiet:
            super().log_message(fmt, *args)

    def _gate(self) -> bool:
        """Auth then rate limit, in that order — an unauthenticated
        client should never learn it was also about to be rate
        limited. Writes the error response itself and returns `False`
        when the request should stop here; every route checks this
        first and returns immediately if it does.
        """
        if self._auth_token and not check_token(
            self.headers.get("Authorization"), self._auth_token
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
        if self._rate_limiter is not None and not self._rate_limiter.allow(
            self.client_address[0]
        ):
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
        self.send_header("Content-Security-Policy", self._csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for name, value in cors_headers(
            self.headers.get("Origin"), self._cors_origins
        ).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, markup: str, status: int = 200) -> None:
        self._send(status, markup.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
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

    def _bad_request(self, wants_json: bool, error: str, lang: str) -> None:
        """A 400 answered in the client's own content type.

        Both callers need this shape for the reason the second one's comment
        gives: a page that posts a form and gets `{"error": ...}` back is
        the no-JavaScript path breaking.
        """
        if wants_json:
            self._json({"error": error}, status=400)
        else:
            self._html(render_page(lang), status=400)

    # --- routes ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self._gate():
            return
        route = urlparse(self.path)
        if route.path == "/":
            query = parse_qs(route.query)
            lang_values = query.get("lang")
            lang = _resolve_lang(
                lang_values[0] if lang_values else None, self._cfg.default_lang
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

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if not self._gate():
            return
        route = urlparse(self.path).path
        if route == "/ask":
            self._handle_ask()
        elif route == "/follow-up" and self._followup_store is not None:
            self._handle_followup()
        else:
            self._html("<h1>404</h1>", status=404)

    # --- POST /ask, in the order the request is read --------------------

    def _ask_submission(
        self, raw: bytes, wants_json: bool
    ) -> tuple[dict[str, Any], str, str] | None:
        """The question and language a request asked with, from whichever of
        the two body shapes it sent, or `None` when a JSON body could not be
        read at all — in which case the 400 has already been written and the
        caller has nothing left to do.

        A form submission comes back with an empty submission dict rather
        than its own parsed fields. `history` and `stream` are JSON-caller
        features and a form field of either name has never meant anything
        here, so there is nothing in `fields` a later step should be able to
        reach for.
        """
        if wants_json:
            try:
                submitted = _json_object(raw)
            except ValueError:
                self._json({"error": "malformed JSON body"}, status=400)
                return None
            question = str(submitted.get("question") or "")
            lang = _resolve_lang(submitted.get("lang"), self._cfg.default_lang)
            return submitted, question.strip(), lang
        fields = parse_qs(raw.decode("utf-8"))
        question = (fields.get("question") or [""])[0]
        lang_values = fields.get("lang")
        lang = _resolve_lang(
            lang_values[0] if lang_values else None, self._cfg.default_lang
        )
        return {}, question.strip(), lang

    def _ask_session(self, submitted: dict[str, Any]) -> Session | None:
        """The conversation this request wants resolved against, or `None`
        when it is a single-turn request.

        Conversation state lives entirely with the client: a JSON caller may
        attach its history (prior questions and the passage ids they were
        answered from) and this request resolves the follow-up against it.
        The server reconstructs a Session per call and stores nothing — same
        stance as "no state, no storage" in the module docstring, applied to
        conversations. The no-JavaScript form path stays single-turn by
        construction: it arrives here with an empty submission, so there is
        no history for it to have.
        """
        history = submitted.get("history")
        if isinstance(history, dict):
            return Session.from_payload(history)
        return None

    def _ask_turn(
        self, session: Session | None, question: str, lang: str
    ) -> tuple[AskResult, dict[str, Any] | None]:
        """The answer, and the turn metadata a session request also reports.

        `None` metadata means the request carried no history at all, and is
        what keeps the `turn` key out of a single-turn payload.
        """
        if session is not None:
            turn_result = session.ask(question, self._index, self._cfg, lang=lang)
            return turn_result.result, {
                "resolved_with_context": turn_result.resolved_with_context,
                "context_from_turns": list(turn_result.context_from_turns),
                "context_terms": list(turn_result.context_terms),
            }
        return ask(question, self._index, self._cfg, lang=lang), None

    def _send_stream(self, answer: Answer) -> None:
        """The answer as server-sent events over a close-delimited body: no
        Content-Length is possible for a stream, and HTTP/1.1 makes
        that legal exactly when `Connection: close` says the end of the
        response *is* the end of the body. The frames are
        cairn.stream's own, so a CLI --stream run and this endpoint
        emit byte-identical sequences.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            for frame in sse_stream(answer):
                self.wfile.write(frame.encode("utf-8"))

    def _ask_payload(
        self,
        result: AskResult,
        turn_meta: dict[str, Any] | None,
        offer_followup: bool,
    ) -> dict[str, Any]:
        """The JSON body for an answered question: the answer's own payload,
        plus the three keys only a server can know to add.
        """
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
        return payload

    def _handle_ask(self) -> None:
        raw = self._read_body()
        wants_json = "application/json" in (self.headers.get("Content-Type") or "")
        submission = self._ask_submission(raw, wants_json)
        if submission is None:
            return
        submitted, question, lang = submission

        if not question:
            self._bad_request(wants_json, "empty question", lang)
            return

        try:
            session = self._ask_session(submitted)
        except EngineError as exc:
            self._json({"error": str(exc)}, status=400)
            return

        try:
            result, turn_meta = self._ask_turn(session, question, lang)
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
            self._bad_request(wants_json, str(exc), self._cfg.default_lang)
            return

        if self._refusal_counter is not None and result.answer.kind == "refusal":
            # lang and a fixed reason code only — never the question.
            # See cairn/refusal_stats.py's module docstring for why that
            # boundary is structural rather than a promise about this
            # one call site.
            self._refusal_counter.record(lang, refusal_reason(result.answer.trace))

        offer_followup = self._followup_store is not None and result.answer.kind == "refusal"

        if wants_json and submitted.get("stream"):
            self._send_stream(result.answer)
            return

        if wants_json:
            self._json(self._ask_payload(result, turn_meta, offer_followup))
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
                submitted = _json_object(raw)
            except ValueError:
                self._json({"error": "malformed JSON body"}, status=400)
                return
            contact = str(submitted.get("contact") or "").strip()
            question = str(submitted.get("question") or "").strip()
            lang = _resolve_lang(submitted.get("lang"), self._cfg.default_lang)
            include_question = bool(submitted.get("include_question"))
        else:
            fields = parse_qs(raw.decode("utf-8"))
            contact = (fields.get("contact") or [""])[0].strip()
            question = (fields.get("question") or [""])[0].strip()
            lang_values = fields.get("lang")
            lang = _resolve_lang(
                lang_values[0] if lang_values else None, self._cfg.default_lang
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

        assert self._followup_store is not None  # do_POST only reaches here if so
        self._followup_store.record(
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

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
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
        headers = cors_headers(self.headers.get("Origin"), self._cors_origins)
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
) -> type[BaseHTTPRequestHandler]:
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

    class BoundHandler(CairnHandler):
        """:class:`CairnHandler` with one server's configuration filled in.

        A fresh subclass per call, because the attributes are class-level
        and two servers in one process — which the tests routinely run —
        must not be able to see each other's index.
        """

        _cfg = cfg
        _index = index
        _quiet = quiet
        _csp = csp
        _auth_token = auth_token
        _rate_limiter = rate_limiter
        _cors_origins = cors_origins
        _refusal_counter = refusal_counter
        _followup_store = followup_store

    return BoundHandler


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
) -> ThreadingHTTPServer:
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
