#!/usr/bin/env python3
"""Fail when the page GitHub Pages serves is not the page this checkout publishes.

`site_build.py --check` proves the committed `site/index.html` is what the
committed evidence produces. `tests/test_site.py` proves the page quotes that
evidence. Both grade the checkout. Nothing graded the bytes a reader receives,
so a deploy that never ran, ran from an older commit, or dropped a file would
leave every gate green while the published page said something else. That gap
is not hypothetical: it is the one that let a sibling repository serve a page
older than the evidence pipeline that was supposed to have produced it.

This closes it from the other end. It regenerates the page from the checkout,
fetches the live page over HTTPS, and fails naming every byte-level difference.

    python3 verify_live_site.py            # on demand, from a clean checkout
    python3 verify_live_site.py --help     # the knobs

Vacuity is the failure mode a check like this is most exposed to, so three
things are refused outright instead of being reported as a pass:

  * an empty or short comparison set, because a sentinel that compares nothing
    and prints OK is worse than no sentinel at all (`--minimum`);
  * any fetch that does not return HTTP 200, including a host that is simply
    unreachable;
  * an origin that answers a guaranteed-missing path with anything but 404,
    which is how a catch-all would make every matching comparison meaningless.

Exit codes: 0 the live page is the published page, 1 it is not, 4 the check
could not run.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import secrets
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent

# The published origin. `site/` is uploaded whole by .github/workflows/pages.yml,
# so `site/index.html` is served at the base path and every other file under
# `site/` is served at its path below it.
LIVE_URL = "https://chelseakr.github.io/cairn/"
PUBLISHED_DIR = REPO / "site"

# One page is published today. The floor is what stops the comparison set from
# quietly emptying: if `site/` is ever pruned to nothing, or this script is
# pointed somewhere it finds no files, that is a failure and not a pass.
MINIMUM_FILES = 1

MAXIMUM_FILE_BYTES = 16 * 1024 * 1024
EXIT_DIFFERS = 1
EXIT_CANNOT_RUN = 4


class LiveSiteError(RuntimeError):
    """The live page could not be verified against the checkout."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class Origin:
    """Bounded HTTPS reads from one fixed public origin. Redirects are not followed."""

    def __init__(self, url: str, *, timeout_seconds: float) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise LiveSiteError(f"live URL {url!r} is not a canonical HTTPS origin")
        if not 1.0 <= timeout_seconds <= 60.0:
            raise LiveSiteError("timeout must be between 1 and 60 seconds")
        self.host = parts.hostname
        self.base = parts.path.rstrip("/")
        self.url = url
        self._timeout = timeout_seconds

    def target(self, relative: str, nonce: str) -> str:
        if relative.startswith("/") or "?" in relative or "#" in relative:
            raise LiveSiteError(f"relative path {relative!r} is not canonical")
        return f"{self.base}/{relative}?live-integrity={nonce}"

    def get(
        self,
        relative: str,
        *,
        nonce: str,
        maximum_bytes: int = MAXIMUM_FILE_BYTES,
    ) -> Response:
        target = self.target(relative, nonce)
        # The audit rule below is about HTTPSConnection used without certificate
        # verification: Python before 3.4.3 did not verify by default. This call
        # passes ssl.create_default_context(), which verifies both the chain and
        # the hostname, and is the condition the rule exists to require.
        # nosemgrep: httpsconnection-detected
        connection = http.client.HTTPSConnection(
            self.host, timeout=self._timeout, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-cache, no-store, max-age=0",
                    "Pragma": "no-cache",
                    "User-Agent": "cairn-live-integrity/1",
                },
            )
            response = connection.getresponse()
            encoding = response.getheader("Content-Encoding")
            if encoding not in {None, "identity"}:
                raise LiveSiteError(f"{target} came back {encoding}-encoded, not identity")
            body = response.read(maximum_bytes + 1)
            if len(body) > maximum_bytes:
                raise LiveSiteError(f"{target} exceeds the {maximum_bytes} byte read limit")
            return Response(status=response.status, body=body)
        except (OSError, http.client.HTTPException) as exc:
            raise LiveSiteError(f"GET https://{self.host}{target} failed: {exc}") from exc
        finally:
            connection.close()


def short(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def regenerate_from_the_checkout() -> None:
    """Refuse to compare against a committed page the code no longer produces."""
    result = subprocess.run(
        [sys.executable, str(REPO / "site_build.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LiveSiteError(
            "site_build.py --check failed, so the committed page is not what the code "
            "produces and there is nothing trustworthy to compare the live page with:\n"
            f"{result.stdout}{result.stderr}"
        )


def published_inventory() -> dict[str, bytes]:
    """Every file the deploy uploads, keyed by the path it is served at."""
    if not PUBLISHED_DIR.is_dir():
        raise LiveSiteError(f"{PUBLISHED_DIR} is not a directory")
    inventory: dict[str, bytes] = {}
    for path in sorted(PUBLISHED_DIR.rglob("*")):
        if path.is_symlink():
            raise LiveSiteError(f"{path} is a symlink; refusing to publish-compare it")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if not payload:
            raise LiveSiteError(f"{path} is empty; that is not a page worth comparing")
        inventory[path.relative_to(PUBLISHED_DIR).as_posix()] = payload
    return inventory


def prove_the_origin_discriminates(origin: Origin, nonce: str) -> None:
    """A host that answers everything with 200 makes every comparison vacuous."""
    missing = f".live-integrity-guaranteed-missing-{nonce}"
    response = origin.get(missing, nonce=nonce, maximum_bytes=1024 * 1024)
    if response.status != 404:
        raise LiveSiteError(
            f"the origin answered a guaranteed-missing path with HTTP {response.status} "
            f"instead of 404, so a matching fetch would prove nothing: /{missing}"
        )


def compare(origin: Origin, inventory: dict[str, bytes], nonce: str) -> list[str]:
    differences: list[str] = []
    for relative, expected in sorted(inventory.items()):
        response = origin.get(relative, nonce=nonce)
        if response.status != 200:
            differences.append(
                f"{relative}: the live origin returned HTTP {response.status}; "
                f"the checkout publishes {len(expected)} bytes"
            )
            continue
        if response.body != expected:
            differences.append(
                f"{relative}: live sha256 {short(response.body)} "
                f"({len(response.body)} bytes) is not the published "
                f"{short(expected)} ({len(expected)} bytes)"
            )
    # The base path has to serve the index document too: a deploy that uploads
    # the file but stops serving the directory is still a broken publication.
    index = inventory.get("index.html")
    if index is not None:
        root = origin.get("", nonce=nonce)
        if root.status != 200:
            differences.append(f"/: the live origin returned HTTP {root.status}")
        elif root.body != index:
            differences.append(
                f"/: live sha256 {short(root.body)} is not the published index.html "
                f"{short(index)}"
            )
    return differences


def refuse_an_empty_comparison(count: int, minimum: int, what: str) -> None:
    """A check that compares nothing must fail, not pass."""
    if count < minimum:
        raise LiveSiteError(
            f"{what} holds {count} file(s), below the floor of {minimum}. "
            f"A check that compares nothing must fail, not pass."
        )


def refuse_unbounded_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Bounds on the knobs, so a typo cannot quietly turn the check into nothing."""
    if not 1 <= args.attempts <= 10:
        parser.error("--attempts must be between 1 and 10")
    if not 0 <= args.retry_seconds <= 120:
        parser.error("--retry-seconds must be between 0 and 120")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=LIVE_URL, help=f"live site root (default {LIVE_URL})")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--minimum",
        type=int,
        default=MINIMUM_FILES,
        help="refuse to pass on fewer published files than this",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="compare the committed site/ without first regenerating it",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="how many times to look before reporting a difference (default 3)",
    )
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=20.0,
        help="seconds to wait between attempts, for a deploy to settle (default 20)",
    )
    args = parser.parse_args(argv)
    refuse_unbounded_options(parser, args)

    last_error: LiveSiteError | None = None
    differences: list[str] = []
    for attempt in range(1, args.attempts + 1):
        last_error = None
        try:
            if not args.skip_rebuild:
                regenerate_from_the_checkout()
            inventory = published_inventory()
            refuse_an_empty_comparison(len(inventory), args.minimum, "the comparison set")
            origin = Origin(args.url, timeout_seconds=args.timeout_seconds)
            nonce = secrets.token_hex(16)
            prove_the_origin_discriminates(origin, nonce)
            differences = compare(origin, inventory, nonce)
        except LiveSiteError as exc:
            last_error = exc
            differences = []
        if last_error is None and not differences:
            break
        if attempt < args.attempts:
            reason = last_error if last_error else f"{len(differences)} difference(s)"
            print(
                f"attempt {attempt}/{args.attempts}: {reason}; waiting "
                f"{args.retry_seconds:.0f}s in case a deploy is still settling",
                file=sys.stderr,
            )
            time.sleep(args.retry_seconds)
    if last_error is not None:
        print(f"live integrity check could not run: {last_error}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if differences:
        print(
            f"The live page at {origin.url} is not what this checkout publishes.",
            file=sys.stderr,
        )
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        print(
            "\nRe-run the pages workflow to publish the committed site/, or find out why "
            "the deployment is behind it.",
            file=sys.stderr,
        )
        return EXIT_DIFFERS

    print(
        f"{origin.url} serves exactly what this checkout publishes: "
        f"{len(inventory)} file(s), {sum(len(v) for v in inventory.values())} bytes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
