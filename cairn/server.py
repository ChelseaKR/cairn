"""The local web server behind ``cairn serve``.

``http.server`` from the standard library, because the demo path has to run on
a laptop with no network and no install step. It is a demonstration server: it
binds to localhost by default, keeps no state, stores nothing, and logs
nothing about the questions people ask.

The content security policy is deliberately absolute — ``default-src 'none'``
with same-origin styles, scripts and fetches — so the offline claim is
enforced by the browser rather than asserted in a README. If a future change
adds a font from a CDN, the page breaks loudly instead of quietly requiring
the network.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cairn import __version__
from cairn.config import Config
from cairn.engine import EngineError, ask
from cairn.index import Index
from cairn.messages import CATALOGUE
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


def build_handler(cfg: Config, index: Index, *, quiet: bool = False):
    """A request handler class bound to one configuration and index."""

    class CairnHandler(BaseHTTPRequestHandler):
        server_version = f"cairn/{__version__}"
        protocol_version = "HTTP/1.1"

        # --- plumbing ---------------------------------------------------

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            if not quiet:
                super().log_message(fmt, *args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
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
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                return b""
            return self.rfile.read(length)

        # --- routes -----------------------------------------------------

        def do_GET(self):  # noqa: N802 - stdlib naming
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
            if urlparse(self.path).path != "/ask":
                self._html("<h1>404</h1>", status=404)
                return
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
                lang = _resolve_lang((fields.get("lang") or [None])[0], cfg.default_lang)

            question = question.strip()
            if not question:
                if wants_json:
                    self._json({"error": "empty question"}, status=400)
                else:
                    self._html(render_page(lang), status=400)
                return

            try:
                result = ask(question, index, cfg, lang=lang)
            except EngineError as exc:  # pragma: no cover - lang is validated above
                self._json({"error": str(exc)}, status=400)
                return

            if wants_json:
                self._json(result.answer.to_payload())
            else:
                self._html(
                    render_page(lang, turns=turn_markup(question, result, lang))
                )

    return CairnHandler


def serve(cfg: Config, index: Index, *, host: str = "127.0.0.1", port: int = 8765):
    """Build a server. The caller decides when to start serving."""
    return ThreadingHTTPServer((host, port), build_handler(cfg, index))
