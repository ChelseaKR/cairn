"""`cairn.retrieve` functions tested directly against constructed fixtures,
below the level of a full `ask()` — `single_term_scores`, used by `cairn
lint`'s reachability check."""

from __future__ import annotations

import unittest

from cairn.index import IndexedPassage, LanguageStats
from cairn.retrieve import single_term_scores


def passage(term_counts: dict[str, int]) -> IndexedPassage:
    return IndexedPassage(
        passage_id="t#1", doc_id="t", title="T", lang="en", text="body", term_counts=term_counts
    )


class TestSingleTermScores(unittest.TestCase):
    def test_every_held_term_gets_a_score(self):
        p = passage({"aaaaa": 1, "bbbbb": 2})
        stats = LanguageStats(passage_count=10, doc_freq={"aaaaa": 3, "bbbbb": 5})
        scores = single_term_scores(p, stats)
        self.assertEqual(set(scores), {"aaaaa", "bbbbb"})
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores.values()))

    def test_a_passage_with_no_terms_scores_nothing(self):
        p = passage({})
        stats = LanguageStats(passage_count=10, doc_freq={})
        self.assertEqual(single_term_scores(p, stats), {})

    def test_a_suppressed_term_scores_zero(self):
        # `MAX_DF_RATIO` suppresses a term over half a language's passages;
        # a query of exactly that term should score 0.0 against it.
        p = passage({"common": 1, "rare": 1})
        stats = LanguageStats(passage_count=10, doc_freq={"common": 8, "rare": 1})
        scores = single_term_scores(p, stats)
        self.assertEqual(scores["common"], 0.0)
        self.assertGreater(scores["rare"], 0.0)

    def test_many_shared_terms_dilute_every_single_term_score(self):
        # A passage of many equally-common, equally-weighted terms: no one
        # of them can carry the passage on its own, because each contributes
        # only a small slice of the passage's own norm. Concretely, N terms
        # at identical weight give a single-term cosine of 1/sqrt(N).
        terms = {f"term{i:03d}": 1 for i in range(40)}
        p = passage(terms)
        doc_freq = dict.fromkeys(terms, 5)  # same df for every term
        stats = LanguageStats(passage_count=100, doc_freq=doc_freq)
        scores = single_term_scores(p, stats)
        best = max(scores.values())
        self.assertAlmostEqual(best, 1 / (40**0.5), places=6)
        self.assertLess(best, 0.165, "below the shipped default threshold")


if __name__ == "__main__":
    unittest.main()
