"""`collect_queries.py`: candidate questions from public sources. Offline;
the network is injected, and the draw is deterministic."""

from __future__ import annotations

import contextlib
import io
import tempfile
import tomllib
import unittest
from pathlib import Path

import collect_queries
from cairn.record import RecordError, load_questions

QUERIES = [
    "how long does it take to get food stamps",
    "what is the income guideline for wic",
    "ages to collect social security benefits",
    "how much is the vehicle registration fee",
    "how much is it to renew driver's license edgewater fl",
    "when can you enroll covered california",
    "california state disability insurance maximum",
    "how to obtain birth certificate pierce county wa",
    "weather tomorrow",
    "ssi",  # too short
    "How Long Does It Take To Get Food Stamps",  # duplicate after folding
    "what paperwork do i need to file taxes if i have a college student",
    "fee for naturalization",
]


class TestTopics(unittest.TestCase):
    def test_program_vocabulary_in_the_words_people_use(self):
        self.assertEqual(collect_queries.topics_of("how do i get food stamps"), ["food"])
        self.assertEqual(collect_queries.topics_of("CalFresh income limit"), ["food"])
        self.assertEqual(collect_queries.topics_of("medi-cal renewal"), ["health"])
        self.assertEqual(collect_queries.topics_of("weather tomorrow"), [])

    def test_a_query_can_touch_two_topics_and_the_first_wins(self):
        topics = collect_queries.topics_of("does medicare count as welfare")
        self.assertEqual(topics[0], "health")
        self.assertIn("cash-work", topics)


class TestSelectMsmarco(unittest.TestCase):
    def test_stratified_deduplicated_and_california_kept_whole(self):
        items = collect_queries.select_msmarco(QUERIES, per_topic=1, seed=1)
        prompts = [i["prompt"] for i in items]
        # Every California-naming query is kept, regardless of per_topic.
        self.assertIn("when can you enroll covered california", prompts)
        self.assertIn("california state disability insurance maximum", prompts)
        # Off-topic, too short, and the case-folded duplicate are gone.
        self.assertNotIn("weather tomorrow", prompts)
        self.assertNotIn("ssi", prompts)
        self.assertEqual(
            sum(p.lower() == "how long does it take to get food stamps" for p in prompts), 1
        )
        by_prompt = {i["prompt"]: i for i in items}
        self.assertTrue(by_prompt["when can you enroll covered california"]["names_california"])
        self.assertEqual(
            by_prompt["when can you enroll covered california"]["source"], "search-query"
        )

    def test_other_state_is_flagged(self):
        items = collect_queries.select_msmarco(QUERIES, per_topic=10, seed=1)
        by_prompt = {i["prompt"]: i for i in items}
        # "wa" is not matched; only full state names are.
        wa = by_prompt["how to obtain birth certificate pierce county wa"]
        self.assertFalse(wa["names_other_state"])
        ssa = by_prompt["ages to collect social security benefits"]
        self.assertFalse(ssa["names_other_state"])
        items = collect_queries.select_msmarco(
            ["how do i renew my texas drivers license online"], per_topic=10, seed=1
        )
        self.assertTrue(items[0]["names_other_state"])

    def test_deterministic_for_a_seed(self):
        a = collect_queries.select_msmarco(QUERIES, per_topic=2, seed=7)
        b = collect_queries.select_msmarco(QUERIES, per_topic=2, seed=7)
        self.assertEqual(a, b)


class TestStackExchange(unittest.TestCase):
    def test_attribution_and_dedup_through_an_injected_fetch(self):
        calls: list[str] = []

        def fetch(url: str) -> dict:
            calls.append(url)
            return {
                "quota_remaining": 100,
                "items": [
                    {
                        "question_id": 1,
                        "title": "How long can I keep receiving CalFresh out-of-state?",
                        "link": "https://money.stackexchange.com/q/1",
                        "owner": {"display_name": "asker"},
                    },
                    {
                        "question_id": 2,
                        "title": "Medicare &amp; HSA: what if I get laid off?",
                        "link": "https://money.stackexchange.com/q/2",
                        "owner": {},
                    },
                ],
            }

        items = collect_queries.fetch_stackexchange(
            sites=("money",), per_query=2, fetch=fetch, log=lambda _: None
        )
        # Every (site, phrase) pair was queried once; the two questions appear once.
        self.assertGreater(len(calls), 10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "stackexchange")
        expected = "https://money.stackexchange.com/q/1 by asker, CC BY-SA 4.0"
        self.assertIn(expected, items[0]["attribution"])
        self.assertEqual(items[1]["prompt"], "Medicare & HSA: what if I get laid off?")
        self.assertIn("by unknown", items[1]["attribution"])

    def test_stops_when_the_quota_is_nearly_gone(self):
        def fetch(url: str) -> dict:
            return {"quota_remaining": 2, "items": []}

        lines: list[str] = []
        collect_queries.fetch_stackexchange(
            sites=("money",), per_query=1, fetch=fetch, log=lines.append
        )
        self.assertTrue(any("quota" in line for line in lines))


class TestRender(unittest.TestCase):
    def test_candidates_file_is_toml_that_record_refuses_until_labelled(self):
        items = collect_queries.select_msmarco(QUERIES, per_topic=1, seed=1)
        text = collect_queries.render(items, header=collect_queries.HEADER)
        parsed = tomllib.loads(text)["item"]
        self.assertEqual(len(parsed), len(items))
        self.assertTrue(all(i["id"].startswith("cand-") for i in parsed))
        self.assertTrue(all("behavior" not in i for i in parsed))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.toml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(RecordError):
                load_questions(path)  # unlabelled candidates are not evidence

    def test_quotes_and_backslashes_survive(self):
        items = [
            {
                "prompt": 'can i get "food stamps" \\ today',
                "source": "search-query",
                "topic": "food",
                "names_california": False,
                "names_other_state": False,
                "attribution": "x",
            }
        ]
        parsed = tomllib.loads(collect_queries.render(items, header="# h"))["item"]
        self.assertEqual(parsed[0]["prompt"], 'can i get "food stamps" \\ today')


class TestMain(unittest.TestCase):
    def test_reads_local_msmarco_files_and_writes_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "msmarco"
            d.mkdir()
            for name in collect_queries.MSMARCO_FILES:
                (d / name).write_text(
                    "".join(f"{i}\t{q}\n" for i, q in enumerate(QUERIES)), encoding="utf-8"
                )
            out = Path(tmp) / "cand.toml"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = collect_queries.main(
                    ["--msmarco", str(d), "-o", str(out), "--per-topic", "1", "--seed", "1"]
                )
            self.assertEqual(code, 0)
            self.assertIn("MS MARCO:", stdout.getvalue())
            self.assertTrue(out.is_file())

    def test_nothing_to_do_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = collect_queries.main(["-o", str(Path(tmp) / "x.toml")])
            self.assertEqual(code, 1)
            self.assertIn("nothing to do", err.getvalue())


if __name__ == "__main__":
    unittest.main()
