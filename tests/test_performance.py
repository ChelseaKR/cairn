"""A performance/page-weight budget, gated in `make verify`'s test suite —
closing the exact gap the Standards Conformance table used to name: "no
latency or page-weight budget is measured and none is gated."

Two different kinds of measurement, held to two different kinds of budget:

**Page weight is exact and deterministic.** The served page plus its two
static assets (`app.css`, `app.js`) is a fixed number of bytes for a given
build — no timing, no CI noise — so the budget here is tight relative to the
measured baseline.

**Query latency is neither exact nor deterministic** on a shared CI runner,
so the budget is deliberately generous: wide enough that ordinary runner
noise cannot trip it, and still tight enough to catch a real algorithmic
regression (an accidental O(n^2) path, say) rather than nothing at all. A
budget that flakes teaches people to re-run instead of investigate, which is
worse than no budget at all.

Neither number here claims to be the whole performance picture. Rendering
time in a real browser is `tests/browser/`'s territory; this covers only
what pure Python can measure offline. See also `benchmark_index.py`, which
measures the same kind of thing at much larger synthetic corpus scale,
deliberately unbudgeted and not gated — an absolute latency number at scale
does not survive being run somewhere else, which is exactly why it stays a
tool an operator runs by hand rather than a check like this one.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from cairn.config import Config
from cairn.engine import ask
from cairn.index import build_index
from cairn.language import LANGUAGES
from cairn.ui.page import render_page

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
STATIC = ROOT / "cairn" / "ui" / "static"

# Measured 2026-08-22: the largest rendered page (Arabic, the most
# multi-byte UTF-8 of the four interface languages) is ~5.9KB; app.css
# ~5.0KB; app.js ~10.0KB — about 21KB combined. Budgeted at roughly 2x that,
# so an ordinary content addition does not trip this by accident and a real
# regression (an accidentally inlined asset, a debug dump left in the page)
# still does.
MAX_PAGE_BYTES = 12_000
MAX_CSS_BYTES = 10_000
MAX_JS_BYTES = 20_000
MAX_COMBINED_BYTES = 40_000

# Measured 2026-08-22: ~3.3ms median for one query against the demo corpus
# on this machine. Budgeted two orders of magnitude above that: nowhere near
# "still fast", but far enough that ordinary CI runner noise cannot trip it,
# while an accidental linear-becomes-quadratic regression still would.
MAX_QUERY_MS = 500.0


class TestPageWeight(unittest.TestCase):
    """Deterministic: no timing, so the budget here is tight."""

    def test_static_assets_stay_under_budget(self):
        css_bytes = (STATIC / "app.css").read_bytes()
        js_bytes = (STATIC / "app.js").read_bytes()
        self.assertLessEqual(len(css_bytes), MAX_CSS_BYTES)
        self.assertLessEqual(len(js_bytes), MAX_JS_BYTES)

    def test_every_rendered_page_stays_under_budget(self):
        for code in LANGUAGES:
            with self.subTest(lang=code):
                page_bytes = render_page(code).encode("utf-8")
                self.assertLessEqual(len(page_bytes), MAX_PAGE_BYTES)

    def test_combined_weight_stays_under_budget(self):
        # The number a person actually experiences: page plus both assets,
        # for the heaviest interface language.
        heaviest_page = max(len(render_page(code).encode("utf-8")) for code in LANGUAGES)
        combined = (
            heaviest_page
            + len((STATIC / "app.css").read_bytes())
            + len((STATIC / "app.js").read_bytes())
        )
        self.assertLessEqual(combined, MAX_COMBINED_BYTES)


class TestQueryLatency(unittest.TestCase):
    """Not deterministic on a shared runner, so the budget is deliberately
    wide — see the module docstring."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DEMO)
        cls.cfg = Config()

    def test_a_grounded_query_answers_within_budget(self):
        question = "How much is the monthly grocery allowance for one person?"
        t0 = time.perf_counter()
        result = ask(question, self.index, self.cfg)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(result.answer.kind, "grounded")
        self.assertLessEqual(
            elapsed_ms,
            MAX_QUERY_MS,
            f"a single demo-corpus query took {elapsed_ms:.1f}ms, over the "
            f"{MAX_QUERY_MS}ms budget",
        )

    def test_a_refusal_answers_within_budget(self):
        # A refusal still scores every candidate against the whole corpus
        # before deciding nothing clears the threshold — the same cost
        # shape as a grounded answer, worth budgeting separately.
        question = "What vaccinations does my dog need?"
        t0 = time.perf_counter()
        result = ask(question, self.index, self.cfg)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(result.answer.kind, "refusal")
        self.assertLessEqual(elapsed_ms, MAX_QUERY_MS)


if __name__ == "__main__":
    unittest.main()
