"""`sweep.py`: the answer-rate / wrong-answer-rate curve. The classifier is
tested on synthetic evidence; the engine-facing path is tested against the
demo corpus and the committed evidence question set, where the two known
open findings (`ck-015`, `ck-022`) must come out by name."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import sweep
from cairn.config import load_config
from cairn.index import build_and_write, read_index
from cairn.record import load_questions

REPO = Path(__file__).resolve().parent.parent


def _scored(
    behavior: str,
    answering: tuple[str, ...],
    candidates: tuple[tuple[str, float], ...],
    **labels,
) -> sweep.Scored:
    return sweep.Scored(
        id="q",
        behavior=behavior,
        answering=frozenset(answering),
        candidates=candidates,
        cross_language=False,
        labels=labels,
    )


class TestOutcomes(unittest.TestCase):
    def test_four_cells(self):
        answer_ok = _scored("answer", ("d.2",), (("d.2", 0.5), ("d.1", 0.3)))
        answer_wrong = _scored("answer", ("d.2",), (("d.1", 0.5), ("d.2", 0.3)))
        answer_refused = _scored("answer", ("d.2",), (("d.2", 0.1),))
        refuse_ok = _scored("refuse", (), (("d.1", 0.1),))
        refuse_wrong = _scored("refuse", (), (("d.1", 0.5),))
        t = 0.2
        self.assertEqual(sweep.outcome_at(answer_ok, t, 1), "correct-answer")
        self.assertEqual(sweep.outcome_at(answer_wrong, t, 1), "wrong-answer")
        self.assertEqual(sweep.outcome_at(answer_refused, t, 1), "wrong-refusal")
        self.assertEqual(sweep.outcome_at(refuse_ok, t, 1), "correct-refusal")
        self.assertEqual(sweep.outcome_at(refuse_wrong, t, 1), "wrong-answer")

    def test_max_passages_widens_composition(self):
        s = _scored("answer", ("d.2",), (("d.1", 0.5), ("d.2", 0.3)))
        self.assertEqual(sweep.outcome_at(s, 0.2, 1), "wrong-answer")
        self.assertEqual(sweep.outcome_at(s, 0.2, 2), "correct-answer")

    def test_threshold_uses_the_engines_own_comparison(self):
        s = _scored("answer", ("d.2",), (("d.2", 0.165),))
        self.assertEqual(sweep.outcome_at(s, 0.165, 1), "correct-answer")  # >=, not >
        self.assertEqual(sweep.outcome_at(s, 0.1651, 1), "wrong-refusal")

    def test_rates(self):
        r = sweep.Rates.of(
            ["correct-answer", "correct-answer", "wrong-answer", "wrong-refusal"]
            + ["correct-refusal"],
            ["answer", "answer", "answer", "answer", "refuse"],
        )
        self.assertAlmostEqual(r.answer_rate, 2 / 4)
        self.assertAlmostEqual(r.wrong_answer_rate, 1 / 3)
        self.assertEqual(r.counts["correct-refusal"], 1)

    def test_rates_with_nothing_to_divide_are_none_not_zero(self):
        r = sweep.Rates.of(["correct-refusal"], ["refuse"])
        self.assertIsNone(r.answer_rate)
        self.assertIsNone(r.wrong_answer_rate)


class TestClassify(unittest.TestCase):
    LAYERS = {
        "snap-en": "federal",
        "calfresh-en": "california",
        "la-dpss-en": "los-angeles",
        "fresno-dss-en": "fresno",
    }

    def test_no_label_for_a_correct_outcome(self):
        s = _scored("answer", ("d.2",), (("d.2", 0.5),))
        self.assertEqual(sweep.classify(s, 0.2, 1, {}), "")

    def test_vocabulary_gap_when_the_answering_passage_is_not_a_candidate(self):
        s = _scored("answer", ("d.2",), (("e.1", 0.1),))
        self.assertEqual(sweep.classify(s, 0.2, 1, {}), "vocabulary-gap")

    def test_threshold_when_refused_with_the_answer_below_the_bar(self):
        s = _scored("answer", ("d.2",), (("d.2", 0.1),))
        self.assertEqual(sweep.classify(s, 0.2, 1, {}), "threshold")

    def test_wrong_passage_when_outranked_within_a_layer(self):
        s = _scored("answer", ("snap-en.4",), (("snap-en.1", 0.5), ("snap-en.4", 0.4)))
        self.assertEqual(sweep.classify(s, 0.2, 1, self.LAYERS), "wrong-passage")
        # Without layer information the same evidence is still a ranking loss.
        self.assertEqual(sweep.classify(s, 0.2, 1, {}), "wrong-passage")

    def test_wrong_passage_even_when_the_answer_sat_below_the_threshold(self):
        # ck-022's shape: the right paragraph never cleared, another did.
        # Lowering the bar would not reorder them, so it is not `threshold`.
        s = _scored("answer", ("snap-en.2",), (("snap-en.4", 0.18), ("snap-en.2", 0.15)))
        self.assertEqual(sweep.classify(s, 0.165, 1, self.LAYERS), "wrong-passage")

    def test_jurisdiction_mismatch_when_a_higher_layer_outranks_the_county(self):
        s = _scored(
            "answer", ("la-dpss-en.1",), (("snap-en.1", 0.5), ("la-dpss-en.1", 0.4))
        )
        self.assertEqual(sweep.classify(s, 0.2, 1, self.LAYERS), "jurisdiction-mismatch")

    def test_wrong_county_when_another_county_outranks(self):
        s = _scored(
            "answer", ("la-dpss-en.1",), (("fresno-dss-en.1", 0.5), ("la-dpss-en.1", 0.4))
        )
        self.assertEqual(sweep.classify(s, 0.2, 1, self.LAYERS), "wrong-county")

    def test_over_answer_for_a_refuse_question(self):
        s = _scored("refuse", (), (("snap-en.1", 0.5),))
        self.assertEqual(sweep.classify(s, 0.2, 1, self.LAYERS), "over-answer")


class TestSplits(unittest.TestCase):
    def test_rates_split_by_any_extra_label(self):
        scored = [
            _scored("answer", ("d.2",), (("d.2", 0.5),), source="elicited", jurisdiction="la"),
            _scored("answer", ("d.2",), (("d.1", 0.5),), source="forum", jurisdiction="la"),
            _scored("refuse", (), (("d.1", 0.1),), source="forum"),
        ]
        self.assertEqual(sweep.split_keys(scored), ["jurisdiction", "source"])
        by_source = sweep.rates_by_label(scored, "source", 0.2, 1)
        self.assertEqual(by_source["elicited"].answer_rate, 1.0)
        self.assertEqual(by_source["forum"].answer_rate, 0.0)
        self.assertEqual(sum(by_source["forum"].counts.values()), 2)

    def test_thresholds_range_is_inclusive_and_rounded(self):
        self.assertEqual(sweep.thresholds_range(0.1, 0.3, 0.1), [0.1, 0.2, 0.3])
        self.assertEqual(len(sweep.thresholds_range(0.05, 0.40, 0.01)), 36)


class TestAgainstTheDemoCorpus(unittest.TestCase):
    """The committed evidence set against the demo corpus, at the configured
    threshold. The two open findings in DESIGN.md must come out by name; if
    either stops, either the engine changed or this sweep no longer reads
    what the engine does."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = load_config(REPO / "cairn.toml")
        index_path = Path(cls.tmp.name) / "index.json"
        build_and_write(REPO / cfg.corpus_path, index_path)
        cls.cfg = cfg
        cls.index = read_index(index_path, REPO / cfg.corpus_path)
        cls.questions = load_questions(REPO / "plumbline" / "questions.toml")
        cls.scored = sweep.score_questions(cls.questions, cls.index, cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_question_scored_once(self):
        self.assertEqual(len(self.scored), len(self.questions))

    def test_the_known_findings_come_out_by_name(self):
        by_id = {s.id: s for s in self.scored}
        t, k = self.cfg.threshold, self.cfg.max_passages
        self.assertEqual(sweep.outcome_at(by_id["ck-015"], t, k), "wrong-refusal")
        self.assertEqual(sweep.classify(by_id["ck-015"], t, k, {}), "threshold")
        self.assertEqual(sweep.outcome_at(by_id["ck-022"], t, k), "wrong-answer")
        self.assertEqual(sweep.classify(by_id["ck-022"], t, k, {}), "wrong-passage")
        self.assertEqual(
            sweep.composed_at(by_id["ck-022"], t, k), ("housing-relief-en.4",)
        )

    def test_every_other_item_is_correct_at_the_configured_threshold(self):
        t, k = self.cfg.threshold, self.cfg.max_passages
        wrong = sorted(
            s.id for s in self.scored if sweep.outcome_at(s, t, k).startswith("wrong")
        )
        self.assertEqual(wrong, ["ck-015", "ck-022"])

    def test_the_curve_trades_answers_for_refusals_as_the_bar_rises(self):
        rows = sweep.sweep(self.scored, [0.05, 0.165, 0.40], self.cfg.max_passages)
        low, configured, high = (r for _, r in rows)
        self.assertGreater(low.wrong_answer_rate, configured.wrong_answer_rate)
        self.assertGreater(configured.answer_rate, high.answer_rate)
        self.assertEqual(high.counts["wrong-answer"], 0)

    def test_cli_end_to_end(self):
        cfg_path = Path(self.tmp.name) / "cairn.toml"
        cfg_path.write_text(
            f'[corpus]\npath = "{(REPO / self.cfg.corpus_path).as_posix()}"\n'
            f'[index]\npath = "{(Path(self.tmp.name) / "index.json").as_posix()}"\n',
            encoding="utf-8",
        )
        json_out = Path(self.tmp.name) / "curve.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sweep.main(
                [
                    "--config",
                    str(cfg_path),
                    "--questions",
                    str(REPO / "plumbline" / "questions.toml"),
                    "--step",
                    "0.05",
                    "--at",
                    "0.165",
                    "--json",
                    str(json_out),
                ]
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("0.165      0.909         0.048", text)
        self.assertIn("<- configured", text)
        self.assertIn("ck-022       answer  wrong-answer     wrong-passage", text)
        self.assertIn("layers unknown", text)
        self.assertTrue(json_out.is_file())

    def test_cli_error_is_clean(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = sweep.main(["--config", "/nowhere/cairn.toml", "--questions", "x"])
        self.assertEqual(code, 1)
        self.assertIn("sweep: error", err.getvalue())


if __name__ == "__main__":
    unittest.main()
