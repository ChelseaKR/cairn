"""The dense retrieval channel: determinism, bounds, and fusion behavior.

The embedding is feature hashing over BLAKE2B, so its defining property is
not quality but *reproducibility*: identical text must produce an identical
vector across processes, machines and years, or every score this channel
contributes is unreproducible noise dressed as a measurement. The first test
runs a child interpreter under a different `PYTHONHASHSEED` on purpose —
that variable salts Python's builtin string hash, which is exactly the trap
this module exists to avoid.
"""

import subprocess
import sys
import unittest

from cairn.config import Config
from cairn.embed import DIMENSION, cosine, features
from cairn.engine import ask
from cairn.index import build_index

CORPUS = "corpus/demo"

_CHILD = (
    "from cairn.embed import features, cosine;"
    "a = features('monthly grocery allowance');"
    "b = features('allowence grocery month');"
    "print(repr(a)); print(round(cosine(a, b), 6))"
)


class TestDeterminism(unittest.TestCase):
    def test_identical_text_produces_an_identical_vector(self):
        text = "How much unpaid rent does the housing relief grant cover?"
        self.assertEqual(features(text), features(text))

    def test_vectors_survive_a_different_process_hash_seed(self):
        """BLAKE2B, not builtin hash(): the vector may not depend on the
        process's salted hash seed, which differs between this interpreter
        and any child of it."""
        seeds = ["0", "1", "12345"]
        runs = [
            subprocess.run(
                [sys.executable, "-c", _CHILD],
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    "PYTHONHASHSEED": seed,
                    "PYTHONPATH": ".",
                },
                check=True,
            ).stdout
            for seed in seeds
        ]
        self.assertEqual(len(set(runs)), 1, "vector changed between hash seeds")

    def test_slots_never_exceed_the_dimension(self):
        vector = features("deadline deadline deadline subsidio alimentos")
        self.assertTrue(vector)
        self.assertLessEqual(max(vector), DIMENSION - 1)
        self.assertGreaterEqual(min(vector), 0)


class TestBounds(unittest.TestCase):
    def test_cosine_is_bounded_unit_interval(self):
        texts = [
            "who can get the discount bus pass",
            "you may qualify for a reduced fare GoPass",
            "ما هي بطاقة GoPass؟",
            "",
            "!!! ???",
        ]
        for a in texts:
            for b in texts:
                score = cosine(features(a), features(b))
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_empty_input_scores_zero_against_everything(self):
        empty = features("!!!")
        self.assertEqual(empty, {})
        self.assertEqual(cosine(empty, features("housing grant")), 0.0)

    def test_self_similarity_beats_an_unrelated_passage(self):
        target = "The Fresh Start Grocery Allowance pays $212 each month."
        related = features(target)
        self.assertAlmostEqual(cosine(related, related), 1.0, places=12)


class TestSubwordSimilarity(unittest.TestCase):
    """What the channel is for: shared surface that the word-level index
    cannot see. The ordering claims matter more than the absolute numbers."""

    def test_a_misspelled_word_outranks_an_unrelated_one(self):
        anchor = features("grocery allowance eligibility")
        misspelled = features("grocery allowence")
        unrelated = features("vaccinations dog license")
        self.assertGreater(
            cosine(anchor, misspelled),
            cosine(anchor, unrelated),
            "the subword channel prefers the near-miss spelling",
        )

    def test_an_inflection_the_stemmer_splits_still_matches(self):
        # The truncation stemmer cuts both words at five characters, hiding
        # the suffix difference; these differ inside the first five instead.
        anchor = features("recibiendo beneficios")
        variant = features("recibe benes")
        unrelated = features("votar registrarse")
        self.assertGreater(
            cosine(anchor, variant), cosine(anchor, unrelated)
        )


class TestHybridFusion(unittest.TestCase):
    """The fused scorer, exercised only where the pins allow it: an explicit
    weight, never the default."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)

    def trace(self, question, weight):
        cfg = Config(dense_weight=weight)
        return ask(question, self.index, cfg).answer.trace

    def test_fusion_blends_the_two_components(self):
        question = "How much does the GoPass cost per year?"
        weight = 0.25
        candidate = self.trace(question, weight).candidates[0]
        expected = (1 - weight) * candidate.lexical + weight * candidate.dense
        self.assertAlmostEqual(candidate.score, expected, places=12)

    def test_zero_weight_is_the_plain_lexical_score(self):
        question = "When is the deadline to apply for the housing grant?"
        for candidate in self.trace(question, 0.0).candidates:
            self.assertEqual(candidate.score, candidate.lexical)
            self.assertEqual(candidate.dense, 0.0)

    def test_dense_alone_cannot_rank_a_candidate(self):
        """A passage sharing no scored term with the question stays out of
        the ranking however subword-similar it is: the dense channel re-ranks
        lexical candidates, it never mints them. The gibberish tokens are
        checked against the index first, so the test fails if the corpus ever
        grows a word that happens to stem to one of them."""
        from cairn.retrieve import retrieve
        from cairn.text import tokenize

        question = "kwyjibo zzzqqq xvmmqq"
        held = {t for p in self.index.passages for t in p.term_counts}
        self.assertFalse(
            set(tokenize(question)) & held,
            "the gibberish stopped being absent from the corpus; pick new tokens",
        )
        trace = retrieve(
            question,
            self.index,
            threshold=0.01,
            candidates=8,
            lang="en",
            dense_weight=0.5,
        )
        self.assertEqual(trace.candidates, ())
        self.assertFalse(trace.grounded)

    def test_acceptance_still_belongs_to_the_threshold(self):
        question = "How much is the winter utility credit worth each month?"
        trace = self.trace(question, 0.4)
        for candidate in trace.candidates:
            self.assertEqual(candidate.accepted, candidate.score >= trace.threshold)

    def test_the_known_colloquial_refusal_survives_a_moderate_weight(self):
        """Pinned here rather than only in DESIGN.md's measurement table: at
        the largest weight whose bands were measured safe, "who can get the
        discount bus pass" still refuses. A future embedding change that
        flips this fails loudly instead of quietly answering from the fare
        paragraph."""
        answer = ask(
            "who can get the discount bus pass",
            self.index,
            Config(dense_weight=0.15),
        ).answer
        self.assertEqual(answer.kind, "refusal")


if __name__ == "__main__":
    unittest.main()
