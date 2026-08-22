"""Networked-deployment additions to `cairn serve`: auth, rate limiting, and
cross-origin access for an agency embedding Cairn in their own site.

All of it is opt-in and off by default — `cairn serve` with no flags set
behaves exactly as it always has, and SECURITY.md's "not intended to be
exposed to a network" boundary is unchanged for that default path. This
module exists for the moment an operator explicitly asks to move past it,
and it stays small, auditable primitives rather than a framework: auth is
one constant-time comparison, rate limiting is one lock-protected counter
per client address, CORS and iframe embedding are both explicit
origin-allow-lists with no wildcard. All stdlib only — no new runtime
dependency.

None of it is a complete answer to "how do I expose this safely." See
`docs/deployment.md` for what still has to come from outside this process
entirely: TLS termination, a real firewall, and the operational practices
(secret rotation, log review, incident response) that do not fit in a
Python module. Bearer-token auth is *service* protection — appropriate for
a machine caller or a trusted internal deployment behind its own access
control — not a login system for individual end users; see
`docs/deployment.md` for that boundary stated plainly. `docs/embedding.md`
covers CORS and iframe embedding the same way.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass, field
from threading import Lock

BEARER_PREFIX = "Bearer "


def check_token(header_value: str | None, expected: str) -> bool:
    """Constant-time bearer-token check against the `Authorization` header.

    `expected` must be non-empty; the caller decides whether auth is
    enabled at all (an empty token means "off" and is never passed here).
    `hmac.compare_digest` is used because a plain `==` short-circuits on
    the first mismatched byte — a timing side channel on a secret
    comparison is a real, exploitable attack, not a theoretical one.
    """
    if not header_value or not header_value.startswith(BEARER_PREFIX):
        return False
    token = header_value[len(BEARER_PREFIX) :]
    return hmac.compare_digest(token, expected)


@dataclass
class RateLimiter:
    """A fixed-window request counter, per client address, under one lock.

    Deliberately not a token bucket or anything smarter: this is a blunt
    instrument against a client hammering the endpoint, not a fairness
    scheduler, and the simplest correct thing is the one an operator can
    read in thirty seconds and trust. `limit_per_minute <= 0` disables it
    entirely — `allow` always returns `True` without taking the lock.

    In-memory and per-process: restarting `cairn serve` resets every
    client's count, and a client's history is never written anywhere.
    Consistent with the rest of this project's "nothing about a request is
    ever logged" posture, and a real limitation an operator should know —
    see `docs/deployment.md`.
    """

    limit_per_minute: int
    _window_start: dict[str, float] = field(default_factory=dict)
    _count: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def allow(self, client: str, *, now: float | None = None) -> bool:
        if self.limit_per_minute <= 0:
            return True
        current = time.time() if now is None else now
        with self._lock:
            start = self._window_start.get(client)
            if start is None or current - start >= 60.0:
                self._window_start[client] = current
                self._count[client] = 1
                return True
            self._count[client] += 1
            return self._count[client] <= self.limit_per_minute


def cors_headers(origin: str | None, allowed_origins: tuple[str, ...]) -> dict[str, str]:
    """Response headers for one cross-origin request, or `{}` if it should
    get none.

    An empty `allowed_origins` — the default — always returns `{}`, which is
    exactly today's behaviour: no `Access-Control-*` headers at all, so a
    browser refuses a cross-origin `fetch()` the way it always has. A match
    echoes back the *specific requesting origin*, never a `*` wildcard: a
    wildcard cannot be combined with a request that carries an `Authorization`
    header (the bearer token, when auth is enabled) under the CORS spec, and
    an explicit allow-list is also just a closer match to what "an agency's
    own site" means than "any site". `Vary: Origin` is included whenever a
    match is returned, so a cache in front of this server cannot serve one
    origin's allowed response to a different, disallowed one.
    """
    if not origin or origin not in allowed_origins:
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


def frame_ancestors(allowed_origins: tuple[str, ...]) -> str:
    """The CSP `frame-ancestors` directive value for `--allow-embed`.

    `'none'` — today's behaviour, and the CSP's own default before this
    existed — unless an operator has explicitly named origins allowed to put
    this page in an `<iframe>`. No wildcard here either, for the same reason
    as `cors_headers`: this is a list of the specific sites trusted to embed
    the page, not an invitation to anyone who tries.
    """
    if not allowed_origins:
        return "'none'"
    return " ".join(allowed_origins)
