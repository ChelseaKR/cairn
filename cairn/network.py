"""Networked-deployment additions to `cairn serve`: auth and rate limiting.

Both are opt-in and off by default — `cairn serve` with neither flag set
behaves exactly as it always has, and SECURITY.md's "not intended to be
exposed to a network" boundary is unchanged for that default path. This
module exists for the moment an operator explicitly asks to move past it,
and it stays two small, auditable primitives rather than a framework: auth
is one constant-time comparison, rate limiting is one lock-protected
counter per client address, both stdlib only — no new runtime dependency.

Neither is a complete answer to "how do I expose this safely." See
`docs/deployment.md` for what still has to come from outside this process
entirely: TLS termination, a real firewall, and the operational practices
(secret rotation, log review, incident response) that do not fit in a
Python module. This is bearer-token *service* protection — appropriate for
a machine caller or a trusted internal deployment behind its own access
control — not a login system for individual end users; see
`docs/deployment.md` for that boundary stated plainly.
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
