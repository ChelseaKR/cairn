"""Grading the server instead of a recording of it.

Two layers, for the same reason the accessibility checking has two.

Everything in this file runs offline, in the core dev path, with no harness:
the drift it is looking for is between Cairn's own recorder and Cairn's own
server, and that comparison needs neither the auditor nor the network. It
drives a real socket, because a recording that agrees with the server in
process and disagrees over HTTP is exactly the failure being guarded against.

The second layer is `./plumbline-live.sh`, which puts the pinned harness in
the loop: it makes the harness ask the questions over HTTP and seal the
answers, then `live_check.py` compares that bundle to the committed one. What
is tested here is the wiring that run depends on — that the live config grades
to the same bars as the gate, that it points at a field the payload actually
has, and that every way the comparison can be uninformative is reported as
"could not run" rather than as agreement.
"""

import json
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path

import live_check
from cairn.record import bundle_checksums
from tests.test_ui import ServerHarness

ROOT = Path(__file__).resolve().parent.parent
LIVE_CONFIG = ROOT / "plumbline" / "live.toml"
TARGET_CONFIG = ROOT / "plumbline" / "target.toml"
BUNDLE = ROOT / "plumbline" / "bundle"
QUESTIONS = ROOT / "plumbline" / "questions.toml"
SCRIPT = ROOT / "plumbline-live.sh"


def load(path: Path) -> dict:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def workflow_job(name: str) -> str:
    """One job's block out of the workflow, without the jobs after it."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    for offset, line in enumerate(lines[start + 1:], start + 1):
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def responses_of(bundle: Path) -> dict[str, str]:
    return {
        row["id"]: row["response"]
        for row in (
            json.loads(line)
            for line in (bundle / "responses.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


class TestTheServerAnswersWhatTheGateGrades(ServerHarness):
    """The check itself, over a socket, with no harness in the loop.

    `plumbline/bundle` is what every audit report this repository publishes
    describes. It was written by calling the engine in process. This asks the
    same questions of the running server and requires the same bytes back.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.questions = tomllib.loads(QUESTIONS.read_text(encoding="utf-8"))["item"]
        cls.recorded = responses_of(BUNDLE)

    def test_every_recorded_answer_is_what_the_server_says(self):
        for question in self.questions:
            with self.subTest(item=question["id"]):
                payload = self.post_json(
                    {"question": question["prompt"], "lang": question["lang"]}
                )
                self.assertEqual(
                    payload["cited_text"],
                    self.recorded[question["id"]],
                    "the graded evidence and the served interface have diverged",
                )

    def test_the_served_page_is_the_audited_interface_snapshot(self):
        # The accessibility suite scores a snapshot in the bundle. A live
        # recording copies that snapshot across rather than fetching it, so
        # this is the only thing that ties the score to the served page.
        from cairn.record import interface_snapshot

        _, served = self.get("/")
        self.assertEqual(
            interface_snapshot(page=served),
            (BUNDLE / "interface.html").read_text(encoding="utf-8"),
        )

    def test_a_refusal_survives_the_round_trip_with_no_sources(self):
        refusals = [q for q in self.questions if q["behavior"] == "refuse"]
        self.assertTrue(refusals)
        for question in refusals:
            with self.subTest(item=question["id"]):
                payload = self.post_json(
                    {"question": question["prompt"], "lang": question["lang"]}
                )
                self.assertEqual(payload["kind"], "refusal")
                self.assertEqual(payload["sources"], [])
                self.assertEqual(payload["cited_text"], payload["text"])


class TestTheLiveConfigGradesTheSameThing(unittest.TestCase):
    def setUp(self):
        self.live = load(LIVE_CONFIG)
        self.target = load(TARGET_CONFIG)

    def test_the_suites_and_floors_are_the_gate_s(self):
        # Grading the live target to a lower bar than the recorded one would
        # make a difference between them invisible, which is the one thing
        # this whole path exists to see.
        def bars(config):
            return {
                name: (suite.get("enabled"), suite.get("floor"))
                for name, suite in config["suites"].items()
            }

        self.assertEqual(bars(self.live), bars(self.target))

    def test_the_judge_is_the_deterministic_one(self):
        self.assertEqual(self.live["judge"]["kind"], "lexical")

    def test_it_records_from_the_committed_questions(self):
        questions = (LIVE_CONFIG.parent / self.live["adapter"]["questions"]).resolve()
        self.assertEqual(questions, BUNDLE.resolve())

    def test_it_never_writes_over_the_committed_bundle(self):
        out = (LIVE_CONFIG.parent / self.live["dataset"]["path"]).resolve()
        self.assertNotEqual(out, BUNDLE.resolve())
        self.assertIn(".plumbline-live", str(out))
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".plumbline-live/", ignored)

    def test_the_pin_does_not_name_it(self):
        # The gate must not be able to acquire a network dependency by
        # configuration: plumbline.pin names target.toml and nothing else.
        pin = (ROOT / "plumbline.pin").read_text(encoding="utf-8")
        self.assertNotIn("live.toml", pin)

    def test_the_response_pointer_names_a_field_the_payload_has(self):
        # Renaming the payload field and leaving this pointing at the old name
        # is a configuration error the harness would only find at run time,
        # against a live server, which is the worst place to find it.
        from cairn.answer import Answer
        from cairn.retrieve import RetrievalTrace

        empty = Answer(kind="refusal", text="", sources=(),
                       trace=RetrievalTrace(query="", candidates=(), threshold=0.0),
                       lang="en")
        self.assertIn(self.live["adapter"]["response_pointer"], empty.to_payload())

    def test_it_binds_to_loopback(self):
        self.assertIn("127.0.0.1", self.live["adapter"]["endpoint"])

    def test_the_bounds_are_set(self):
        adapter = self.live["adapter"]
        for bound in ("timeout_seconds", "max_response_bytes", "max_items"):
            self.assertIn(bound, adapter)
        self.assertEqual(adapter["on_error"], "abort")
        self.assertGreaterEqual(
            adapter["max_items"],
            len(tomllib.loads(QUESTIONS.read_text(encoding="utf-8"))["item"]),
        )


class ComparisonHarness(unittest.TestCase):
    """A recorded bundle and a live one, both synthetic, on disk."""

    ENDPOINT = "http://127.0.0.1:9999/ask"

    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recorded = self.tmp / "bundle"
        self.live = self.tmp / "live"
        self.recorded.mkdir()
        self.live.mkdir()
        self.answers = {"ck-001": "an answer\n[doc.1]", "ck-002": "another\n[doc.2]"}
        self.write(self.recorded, self.answers)
        checksums = bundle_checksums(self.recorded)
        (self.recorded / "checksums.json").write_text(
            json.dumps(checksums), encoding="utf-8"
        )
        (self.recorded / "interface.html").write_text("<html></html>", encoding="utf-8")
        self.write(self.live, self.answers)
        self.manifest = {
            "recording": {
                "mode": "live",
                "recorded_at": "2026-08-16T00:00:00+00:00",
                "adapter": {"kind": "http_json", "endpoint": self.ENDPOINT},
                "questions": {"sha256": checksums["bundle_sha256"]},
            }
        }
        self.seal()
        self.config = self.tmp / "live.toml"
        self.config.write_text(
            f'[dataset]\npath = "live"\n\n'
            f'[adapter]\nendpoint = "{self.ENDPOINT}"\n',
            encoding="utf-8",
        )

    def write(self, bundle: Path, responses: dict[str, str]) -> None:
        (bundle / "responses.jsonl").write_text(
            "".join(
                json.dumps({"id": k, "response": v}) + "\n" for k, v in responses.items()
            ),
            encoding="utf-8",
        )

    def seal(self) -> None:
        (self.live / "manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def run_check(self):
        return live_check.run(self.config, self.recorded, check_page=False)


class TestTheComparison(ComparisonHarness):
    def test_identical_answers_agree(self):
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_OK)
        self.assertIn("LIVE: MATCH", lines[-1])

    def test_a_changed_answer_is_named_with_both_versions(self):
        self.write(self.live, {**self.answers, "ck-001": "a different answer\n[doc.2]"})
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        report = "\n".join(lines)
        self.assertIn("ck-001", report)
        self.assertIn("a different answer", report)
        self.assertIn("an answer", report)

    def test_an_answer_the_server_did_not_give_is_a_difference(self):
        # Not a smaller sample to average over: an item the live run has no
        # answer for is an item the comparison cannot make.
        self.write(self.live, {"ck-001": self.answers["ck-001"]})
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("answered nothing for: ck-002", "\n".join(lines))

    def test_an_extra_answer_is_reported(self):
        self.write(self.live, {**self.answers, "ck-003": "surprise"})
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("ck-003", "\n".join(lines))

    def test_an_empty_recording_could_not_run(self):
        self.write(self.live, {})
        with self.assertRaises(live_check.CannotRun):
            self.run_check()

    def test_a_bundle_that_never_touched_a_socket_is_not_a_live_one(self):
        self.manifest = {}
        self.seal()
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("no `recording` block", "\n".join(lines))

    def test_the_wrong_adapter_is_reported(self):
        self.manifest["recording"]["adapter"]["kind"] = "subprocess_cli"
        self.seal()
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("not over HTTP", "\n".join(lines))

    def test_a_recording_of_a_different_endpoint_is_reported(self):
        self.manifest["recording"]["adapter"]["endpoint"] = "http://elsewhere/ask"
        self.seal()
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("elsewhere", "\n".join(lines))

    def test_a_recording_of_different_questions_is_not_a_comparison(self):
        self.manifest["recording"]["questions"]["sha256"] = "0" * 64
        self.seal()
        code, lines = self.run_check()
        self.assertEqual(code, live_check.EXIT_DIFFERENT)
        self.assertIn("not comparable", "\n".join(lines))

    def test_no_recording_at_all_could_not_run(self):
        shutil.rmtree(self.live)
        with self.assertRaises(live_check.CannotRun) as caught:
            self.run_check()
        self.assertIn("plumbline-live.sh", str(caught.exception))

    def test_the_cli_reports_could_not_run_as_its_own_exit_code(self):
        shutil.rmtree(self.live)
        code = live_check.main(
            ["--config", str(self.config), "--recorded", str(self.recorded),
             "--no-interface"]
        )
        self.assertEqual(code, live_check.EXIT_CANNOT_RUN)


class TestTheRunnerCannotFetchItsOwnAuditor(unittest.TestCase):
    """The drill, same shape as the gate's in tests/test_interlock.py.

    A live check that resolved the harness itself would be a second way for a
    pinned commit to arrive on a machine, and the one that runs against a
    server rather than committed bytes. It exits 4 instead.
    """

    def run_script(self, env_extra, cwd=None):
        import os

        env = dict(os.environ, **env_extra)
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [str(SCRIPT)], cwd=str(cwd or ROOT), env=env,
            capture_output=True, text=True, timeout=120,
        )

    def test_an_unresolved_harness_exits_four_and_names_the_gate(self):
        import tempfile

        with tempfile.TemporaryDirectory() as empty:
            result = self.run_script({"PLUMBLINE_CACHE_DIR": empty})
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("./plumbline-gate.sh", result.stderr)
        self.assertIn("NOT graded", result.stderr)

    def test_a_missing_pin_exits_four(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                {"PLUMBLINE_PIN_FILE": str(Path(tmp) / "absent.pin")}
            )
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("no pin file", result.stderr)

    def test_an_endpoint_it_cannot_read_exits_four(self):
        # A command substitution that fails still yields an empty string, and
        # `eval ""` succeeds. The runner therefore captures the endpoint
        # before evaluating it, so a config it cannot read is exit 4 rather
        # than a run with the host and port unset.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "live.toml"
            broken.write_text('[adapter]\nendpoint = "nonsense"\n', encoding="utf-8")
            result = self.run_script({"CAIRN_LIVE_CONFIG": str(broken)})
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("usable [adapter].endpoint", result.stderr)

    def test_a_missing_live_config_exits_four(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                {"CAIRN_LIVE_CONFIG": str(Path(tmp) / "absent.toml")}
            )
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("no live target config", result.stderr)


class TestTheRunnerIsNotTheGate(unittest.TestCase):
    def test_it_never_writes_into_the_gate_s_report_directory(self):
        script = SCRIPT.read_text(encoding="utf-8")
        pin = (ROOT / "plumbline.pin").read_text(encoding="utf-8")
        gate_out = [
            line.split("=", 1)[1].strip()
            for line in pin.splitlines()
            if line.strip().startswith("out")
        ]
        self.assertEqual(len(gate_out), 1)
        self.assertNotIn(gate_out[0], script)

    def test_it_says_in_itself_that_it_is_not_the_gate(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NOT THE GATE", script)

    def test_the_gate_workflow_job_does_not_call_it(self):
        # A live check inside the audit job would make the merge gate depend
        # on a server coming up, which is the whole thing being avoided.
        self.assertNotIn("plumbline-live.sh", workflow_job("audit"))

    def test_the_live_job_is_not_something_the_gate_waits_for(self):
        self.assertNotIn("live", workflow_job("audit").split("steps:", 1)[0])


if __name__ == "__main__":
    unittest.main()
