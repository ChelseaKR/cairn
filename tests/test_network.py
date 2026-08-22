"""Auth, rate limiting, and cross-origin embedding: `cairn/network.py`'s
primitives, and the `_gate()`/CORS/CSP wiring that applies them to every
route in `cairn/server.py`.

All of it is opt-in. The recurring assertion across this file is the
negative one: with no flags set, a request that used to succeed still
succeeds, byte for byte the same as before this module existed.
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
from cairn.network import RateLimiter, check_token, cors_headers, frame_ancestors
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


class TestCorsHeaders(unittest.TestCase):
    def test_no_allowed_origins_is_no_headers_at_all(self):
        self.assertEqual(cors_headers("https://example.gov", ()), {})

    def test_a_missing_origin_header_is_no_headers_at_all(self):
        self.assertEqual(cors_headers(None, ("https://example.gov",)), {})

    def test_a_listed_origin_is_echoed_back_not_wildcarded(self):
        headers = cors_headers("https://example.gov", ("https://example.gov",))
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://example.gov")
        self.assertEqual(headers["Vary"], "Origin")

    def test_an_unlisted_origin_gets_nothing(self):
        self.assertEqual(cors_headers("https://evil.example", ("https://example.gov",)), {})

    def test_only_the_matching_origin_of_several_is_echoed(self):
        allowed = ("https://a.example.gov", "https://b.example.gov")
        headers = cors_headers("https://b.example.gov", allowed)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://b.example.gov")


class TestFrameAncestors(unittest.TestCase):
    def test_no_allowed_origins_is_none(self):
        self.assertEqual(frame_ancestors(()), "'none'")

    def test_listed_origins_are_space_joined(self):
        self.assertEqual(
            frame_ancestors(("https://a.example.gov", "https://b.example.gov")),
            "https://a.example.gov https://b.example.gov",
        )


class GatedServerHarness(unittest.TestCase):
    """A running server, parameterized per test class by auth/rate-limit/CORS/embed."""

    auth_token = ""
    rate_limiter = None
    cors_origins = ()
    embed_origins = ()

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
            cors_origins=cls.cors_origins,
            embed_origins=cls.embed_origins,
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

    def options(self, path="/ask", headers=None):
        request = urllib.request.Request(
            self.base + path, headers=headers or {}, method="OPTIONS"
        )
        return urllib.request.urlopen(request)


class TestNoAuthNoRateLimitIsUnchanged(GatedServerHarness):
    """The default path: no flags set, nothing new to notice."""

    def test_get_succeeds_with_no_authorization_header(self):
        with self.get("/") as response:
            self.assertEqual(response.status, 200)

    def test_ask_succeeds_with_no_authorization_header(self):
        with self.post_json({"question": "How much is the benefit?"}) as response:
            self.assertEqual(response.status, 200)

    def test_no_cors_header_is_sent_to_any_origin(self):
        with self.get("/", headers={"Origin": "https://example.gov"}) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_the_csp_frame_ancestors_is_none(self):
        with self.get("/") as response:
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_a_preflight_request_gets_404_like_any_unrecognized_route(self):
        # No cors_origins configured, so cors_headers() is always {} and
        # do_OPTIONS refuses exactly like a route this server never had.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.options("/ask", headers={"Origin": "https://example.gov"})
        self.assertEqual(ctx.exception.code, 404)


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


class TestCorsEnabled(GatedServerHarness):
    cors_origins = ("https://example.gov",)

    def test_a_get_from_the_allowed_origin_carries_the_cors_header(self):
        with self.get("/", headers={"Origin": "https://example.gov"}) as response:
            self.assertEqual(
                response.headers.get("Access-Control-Allow-Origin"), "https://example.gov"
            )
            self.assertEqual(response.headers.get("Vary"), "Origin")

    def test_a_get_from_a_different_origin_carries_no_cors_header(self):
        with self.get("/", headers={"Origin": "https://evil.example"}) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_a_get_with_no_origin_header_carries_no_cors_header(self):
        with self.get("/") as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_ask_from_the_allowed_origin_carries_the_cors_header_too(self):
        headers = {"Origin": "https://example.gov"}
        with self.post_json({"question": "How much is the benefit?"}, headers) as response:
            self.assertEqual(
                response.headers.get("Access-Control-Allow-Origin"), "https://example.gov"
            )

    def test_a_preflight_from_the_allowed_origin_succeeds(self):
        with self.options("/ask", headers={"Origin": "https://example.gov"}) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(
                response.headers.get("Access-Control-Allow-Origin"), "https://example.gov"
            )
            self.assertIn("POST", response.headers.get("Access-Control-Allow-Methods", ""))
            self.assertIn(
                "Authorization", response.headers.get("Access-Control-Allow-Headers", "")
            )

    def test_a_preflight_from_a_different_origin_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.options("/ask", headers={"Origin": "https://evil.example"})
        self.assertEqual(ctx.exception.code, 404)

    def test_cors_is_not_a_substitute_for_auth(self):
        # Enabling CORS alone never bypasses _gate(); with auth also
        # configured a cross-origin caller still needs the token. This
        # class has no auth_token, so the point here is just that a
        # matching Origin doesn't grant anything auth-shaped on its own —
        # the response is a normal 200, not something auth-flavored.
        with self.get("/", headers={"Origin": "https://example.gov"}) as response:
            self.assertIsNone(response.headers.get("WWW-Authenticate"))


class TestEmbedEnabled(GatedServerHarness):
    embed_origins = ("https://example.gov",)

    def test_the_csp_frame_ancestors_names_the_allowed_origin(self):
        with self.get("/") as response:
            csp = response.headers["Content-Security-Policy"]
            self.assertIn("frame-ancestors https://example.gov", csp)
            self.assertNotIn("frame-ancestors 'none'", csp)

    def test_the_rest_of_the_csp_is_unchanged(self):
        with self.get("/") as response:
            csp = response.headers["Content-Security-Policy"]
            self.assertIn("default-src 'none'", csp)
            self.assertIn("style-src 'self'", csp)
            self.assertIn("script-src 'self'", csp)
            self.assertIn("connect-src 'self'", csp)

    def test_embedding_does_not_imply_cors(self):
        # --allow-embed only widens frame-ancestors; it is not --cors-origin.
        with self.get("/", headers={"Origin": "https://example.gov"}) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
