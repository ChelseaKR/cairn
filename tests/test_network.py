"""Auth and rate limiting: `cairn/network.py`'s primitives, and the
`_gate()` wiring that applies them to every route in `cairn/server.py`.

Both are opt-in. The recurring assertion across this file is the negative
one: with neither flag set, a request that used to succeed still succeeds,
byte for byte the same as before this module existed.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from cairn.config import Config
from cairn.index import build_index
from cairn.network import RateLimiter, check_token
from cairn.server import build_handler

DEMO = Path(__file__).resolve().parent.parent / "corpus" / "demo"


class TestCheckToken(unittest.TestCase):
    def test_the_matching_bearer_token_passes(self):
        self.assertTrue(check_token("Bearer secret", "secret"))

    def test_a_wrong_token_fails(self):
        self.assertFalse(check_token("Bearer wrong", "secret"))

    def test_a_missing_header_fails(self):
        self.assertFalse(check_token(None, "secret"))

    def test_a_header_without_the_bearer_prefix_fails(self):
        self.assertFalse(check_token("secret", "secret"))

    def test_basic_auth_is_not_bearer_auth(self):
        self.assertFalse(check_token("Basic c2VjcmV0", "secret"))

    def test_an_empty_header_fails(self):
        self.assertFalse(check_token("", "secret"))

    def test_the_bearer_prefix_alone_with_no_token_fails(self):
        self.assertFalse(check_token("Bearer ", "secret"))


class TestRateLimiter(unittest.TestCase):
    def test_zero_limit_disables_it(self):
        limiter = RateLimiter(0)
        for _ in range(1000):
            self.assertTrue(limiter.allow("1.2.3.4"))

    def test_a_negative_limit_also_disables_it(self):
        limiter = RateLimiter(-1)
        self.assertTrue(limiter.allow("1.2.3.4"))

    def test_requests_within_the_limit_are_allowed(self):
        limiter = RateLimiter(3)
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))

    def test_a_request_past_the_limit_is_refused(self):
        limiter = RateLimiter(3)
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertFalse(limiter.allow("1.2.3.4", now=0.0))

    def test_the_window_resets_after_sixty_seconds(self):
        limiter = RateLimiter(1)
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertFalse(limiter.allow("1.2.3.4", now=30.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=61.0))

    def test_clients_are_counted_independently(self):
        limiter = RateLimiter(1)
        self.assertTrue(limiter.allow("1.2.3.4", now=0.0))
        self.assertTrue(limiter.allow("5.6.7.8", now=0.0))
        self.assertFalse(limiter.allow("1.2.3.4", now=0.0))
        self.assertFalse(limiter.allow("5.6.7.8", now=0.0))


class GatedServerHarness(unittest.TestCase):
    """A running server, parameterized per test class by auth/rate-limit."""

    auth_token = ""
    rate_limiter = None

    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.index = build_index(DEMO)
        handler = build_handler(
            cls.cfg,
            cls.index,
            quiet=True,
            auth_token=cls.auth_token,
            rate_limiter=cls.rate_limiter,
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path="/", headers=None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        return urllib.request.urlopen(request)

    def post_json(self, payload, headers=None):
        merged = {"Content-Type": "application/json"}
        merged.update(headers or {})
        request = urllib.request.Request(
            self.base + "/ask",
            data=json.dumps(payload).encode("utf-8"),
            headers=merged,
        )
        return urllib.request.urlopen(request)


class TestNoAuthNoRateLimitIsUnchanged(GatedServerHarness):
    """The default path: neither flag set, nothing new to notice."""

    def test_get_succeeds_with_no_authorization_header(self):
        with self.get("/") as response:
            self.assertEqual(response.status, 200)

    def test_ask_succeeds_with_no_authorization_header(self):
        with self.post_json({"question": "How much is the benefit?"}) as response:
            self.assertEqual(response.status, 200)


class TestAuthEnabled(GatedServerHarness):
    auth_token = "s3cret"

    def test_the_correct_token_is_let_through(self):
        with self.get("/", headers={"Authorization": "Bearer s3cret"}) as response:
            self.assertEqual(response.status, 200)

    def test_a_missing_token_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/")
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(ctx.exception.headers.get("WWW-Authenticate"), "Bearer")
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body, {"error": "unauthorized"})

    def test_a_wrong_token_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/", headers={"Authorization": "Bearer nope"})
        self.assertEqual(ctx.exception.code, 401)

    def test_ask_also_requires_the_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json({"question": "How much is the benefit?"})
        self.assertEqual(ctx.exception.code, 401)

    def test_ask_succeeds_with_the_token(self):
        headers = {"Authorization": "Bearer s3cret"}
        with self.post_json({"question": "How much is the benefit?"}, headers) as response:
            self.assertEqual(response.status, 200)

    def test_an_unauthenticated_request_is_never_told_it_would_also_be_rate_limited(self):
        # _gate() checks auth before rate limiting; a 401 body carries no
        # trace of rate-limit state.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/")
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertNotIn("rate", json.dumps(body))


class TestRateLimitEnabled(GatedServerHarness):
    rate_limiter = RateLimiter(2)

    def test_requests_within_the_limit_succeed_then_the_next_is_429(self):
        # One test, deliberately: the limiter's state is shared across the
        # whole class (it is bound into the handler once, in setUpClass),
        # so this has to run as one ordered sequence rather than as
        # separate test methods that unittest could reorder alphabetically.
        with self.get("/") as response:
            self.assertEqual(response.status, 200)
        with self.get("/") as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/")
        self.assertEqual(ctx.exception.code, 429)
        self.assertEqual(ctx.exception.headers.get("Retry-After"), "60")
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body, {"error": "rate limit exceeded"})


if __name__ == "__main__":
    unittest.main()
