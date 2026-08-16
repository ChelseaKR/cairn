"""The guard that turns a reported regression into a failed build.

`plumbline-gate.sh` checks floors. These tests cover the two things a floor
does not: a score that fell without breaching one, and a suite that was
switched off so quietly that the gate's own output has nothing to say about
it. Everything here runs offline — the guard reads a report, it does not
produce one — so the core dev path still needs no auditor.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

import audit_guard
from audit_guard import (
    EXIT_CANNOT_RUN,
    EXIT_FINDINGS,
    EXIT_OK,
    assess,
    declared_gaps,
    regression_findings,
)

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "plumbline" / "baseline.json"
TARGET = ROOT / "plumbline" / "target.toml"
PIN = ROOT / "plumbline.pin"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
GUARD = ROOT / "audit_guard.py"


def suite(name, score, floor=0.5, verdict="PASS", n=10):
    return {"suite": name, "score": score, "floor": floor, "verdict": verdict, "n": n}


def baseline_doc(*suites, run_id="run-0"):
    return {
        "format": "plumbline-baseline",
        "format_version": 1,
        "source_run_id": run_id,
        "suites": list(suites),
    }


def report_doc(*suites, run_id="run-1", against="run-0", comparable=True):
    return {
        "target": "cairn-demo",
        "verdict": "PASS",
        "provenance": {"run_id": run_id},
        "suites": list(suites),
        "baseline": {
            "comparable": comparable,
            "summary": "compared",
            "refusals": [],
            "against": {"source_run_id": against},
        },
    }


def blocking(findings):
    return sorted(f.subject for f in findings if f.blocking)


class TestScoreMovement(unittest.TestCase):
    def test_an_unchanged_run_has_nothing_to_say(self):
        before = baseline_doc(suite("accuracy", 0.40))
        now = report_doc(suite("accuracy", 0.40))
        self.assertEqual(regression_findings(now, before), [])

    def test_a_score_that_fell_above_its_floor_still_fails(self):
        # The whole point: 0.36 clears a floor of 0.35, and the gate is green.
        before = baseline_doc(suite("accuracy", 0.40, floor=0.35))
        now = report_doc(suite("accuracy", 0.36, floor=0.35))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), ["accuracy"])
        self.assertIn("0.4000 -> 0.3600", findings[0].detail)

    def test_a_tiny_fall_is_still_a_fall(self):
        # The harness qualifies moves against a minimum detectable effect,
        # because 26 items cannot resolve a wobble. Cairn's runs are
        # deterministic and its evidence is committed, so a move is a change.
        before = baseline_doc(suite("refusal", 0.9615))
        now = report_doc(suite("refusal", 0.9600))
        self.assertEqual(blocking(regression_findings(now, before)), ["refusal"])

    def test_a_score_that_rose_is_a_note_not_a_failure(self):
        before = baseline_doc(suite("accuracy", 0.40))
        now = report_doc(suite("accuracy", 0.44))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), [])
        self.assertIn("baseline is behind", findings[0].detail)

    def test_a_float_round_trip_does_not_invent_a_finding(self):
        before = baseline_doc(suite("fairness", 0.9364))
        now = report_doc(suite("fairness", 0.9364 + 1e-12))
        self.assertEqual(regression_findings(now, before), [])


class TestTheBarItself(unittest.TestCase):
    def test_lowering_a_floor_fails(self):
        before = baseline_doc(suite("accuracy", 0.40, floor=0.35))
        now = report_doc(suite("accuracy", 0.40, floor=0.20))
        self.assertEqual(blocking(regression_findings(now, before)), ["accuracy"])

    def test_raising_a_floor_is_fine(self):
        before = baseline_doc(suite("accuracy", 0.40, floor=0.35))
        now = report_doc(suite("accuracy", 0.40, floor=0.38))
        self.assertEqual(regression_findings(now, before), [])

    def test_a_verdict_flip_is_named_even_though_the_gate_caught_it(self):
        before = baseline_doc(suite("smoke", 1.0, floor=1.0))
        now = report_doc(suite("smoke", 1.0, floor=1.0, verdict="FAIL"))
        self.assertEqual(blocking(regression_findings(now, before)), ["smoke"])


class TestSuitesAppearingAndVanishing(unittest.TestCase):
    def test_a_suite_that_stopped_running_fails(self):
        before = baseline_doc(suite("privacy", 1.0), suite("smoke", 1.0))
        now = report_doc(suite("smoke", 1.0))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), ["privacy"])
        self.assertIn("stopped checking", findings[0].detail)

    def test_a_new_suite_is_a_note(self):
        before = baseline_doc(suite("smoke", 1.0))
        now = report_doc(suite("smoke", 1.0), suite("multilingual", 0.97))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), [])
        self.assertEqual(findings[0].subject, "multilingual")


class TestTheComparisonMustHaveHappened(unittest.TestCase):
    def test_a_run_with_no_baseline_at_all_fails(self):
        now = report_doc(suite("smoke", 1.0))
        now["baseline"] = None
        findings = regression_findings(now, baseline_doc(suite("smoke", 1.0)))
        self.assertEqual(blocking(findings), ["baseline"])
        self.assertIn("nothing would have noticed", findings[0].detail)

    def test_comparing_against_a_different_bar_fails(self):
        before = baseline_doc(suite("smoke", 1.0), run_id="run-committed")
        now = report_doc(suite("smoke", 1.0), against="run-somewhere-else")
        self.assertEqual(blocking(regression_findings(now, before)), ["baseline"])

    def test_a_refused_numeric_comparison_does_not_stop_this_check(self):
        # The harness will not subtract scores once the evidence hash moves.
        # That is exactly when Cairn's answers changed, so this check does.
        before = baseline_doc(suite("accuracy", 0.40))
        now = report_doc(suite("accuracy", 0.10), comparable=False)
        self.assertEqual(blocking(regression_findings(now, before)), ["accuracy"])


class TestDeclaredGaps(unittest.TestCase):
    def test_a_disabled_suite_must_say_what_is_missing_and_whose_it_is(self):
        gaps, findings = declared_gaps({"suites": {"multilingual": {"enabled": False}}})
        self.assertEqual(gaps, [])
        self.assertEqual(blocking(findings), ["multilingual"])

    def test_half_a_declaration_is_not_a_declaration(self):
        _, findings = declared_gaps(
            {"suites": {"multilingual": {"enabled": False, "gap": "no Arabic profile"}}}
        )
        self.assertEqual(blocking(findings), ["multilingual"])
        self.assertIn("fix_belongs_in", findings[0].detail)

    def test_both_kinds_of_finding_come_back_from_one_call(self):
        gaps, findings = assess(
            report_doc(suite("smoke", 0.5)),
            baseline_doc(suite("smoke", 1.0)),
            {"suites": {"multilingual": {"enabled": False}}},
        )
        self.assertEqual(gaps, [])
        self.assertEqual(blocking(findings), ["multilingual", "smoke"])

    def test_a_declared_gap_passes_and_is_reported(self):
        gaps, findings = declared_gaps(
            {
                "suites": {
                    "multilingual": {
                        "enabled": False,
                        "gap": "no Arabic profile in the pinned harness",
                        "fix_belongs_in": "plumbline lexicons.py",
                    },
                    "smoke": {"enabled": True},
                }
            }
        )
        self.assertEqual([g["suite"] for g in gaps], ["multilingual"])
        self.assertEqual(findings, [])


class TestTheCommittedArtifacts(unittest.TestCase):
    """The real files in this repository, not fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        with open(TARGET, "rb") as handle:
            cls.target = tomllib.load(handle)

    def test_the_baseline_is_a_harness_record_not_something_hand_written(self):
        # Deliberately not pinned to one format_version: the harness owns that
        # number and bumping the pin can move it, which is a thing to notice
        # in the diff rather than a test to update mechanically. What is
        # asserted is what a hand-written file would not have.
        self.assertEqual(self.baseline["format"], "plumbline-baseline")
        self.assertIsInstance(self.baseline["format_version"], int)
        for key in ("source_run_id", "dataset_sha256", "judge_config_sha256", "suites"):
            self.assertIn(key, self.baseline)
        for key in ("dataset_sha256", "judge_config_sha256"):
            self.assertRegex(self.baseline[key], r"^[0-9a-f]{64}$")
        self.assertTrue(self.baseline["suites"])
        for entry in self.baseline["suites"]:
            self.assertEqual(
                sorted(entry), ["floor", "n", "score", "suite", "verdict"]
            )

    def test_the_pin_points_at_the_committed_baseline(self):
        pin = PIN.read_text(encoding="utf-8")
        active = [line.split("#", 1)[0] for line in pin.splitlines()]
        settings = dict(
            (part.strip() for part in line.split("=", 1))
            for line in active
            if "=" in line
        )
        self.assertEqual(settings.get("baseline"), "plumbline/baseline.json")

    def test_every_enabled_suite_is_pinned_in_the_baseline(self):
        # Enabling a suite without recording its score would leave a new check
        # with no bar under it. The guard reports that as a note at gate time;
        # this catches it offline, before anyone needs the network.
        enabled = {
            suite_id
            for suite_id, spec in self.target.get("suites", {}).items()
            if spec.get("enabled", True)
        }
        pinned = {entry["suite"] for entry in self.baseline["suites"]}
        self.assertEqual(enabled, pinned)

    def test_no_suite_is_disabled_without_a_declared_gap(self):
        gaps, findings = declared_gaps(self.target)
        self.assertEqual(findings, [], "a suite is switched off and says nothing about it")
        for gap in gaps:
            self.assertIn("plumbline", gap["fix_belongs_in"] + gap["gap"])

    def test_the_declared_gaps_are_also_written_where_a_reader_will_see_them(self):
        # A gap declared only in a config file is a gap declared to nobody.
        # Both documents must carry a line that names the suite and says it is
        # not scored — the phrase is the contract; the prose around it is free.
        gaps, _ = declared_gaps(self.target)
        for name in ("README.md", "DESIGN.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for gap in gaps:
                stated = [
                    para for para in text.split("\n\n")
                    if gap["suite"] in para and "not scored" in para
                ]
                self.assertTrue(
                    stated,
                    f"{name} never says the {gap['suite']} suite is not scored; a "
                    f"reader would take the gate's 'all suites passed' at face value",
                )


class TestRunningIt(unittest.TestCase):
    def write(self, tmp: Path, report: dict, baseline: dict, target: str) -> None:
        (tmp / "audits" / "run").mkdir(parents=True)
        (tmp / "audits" / "run" / "report.json").write_text(json.dumps(report))
        (tmp / "baseline.json").write_text(json.dumps(baseline))
        (tmp / "target.toml").write_text(target, encoding="utf-8")

    def invoke(self, tmp: Path, *extra: str) -> int:
        # The guard is a build-log tool; its report belongs in a build log,
        # not in the middle of this suite's output.
        with contextlib.redirect_stdout(io.StringIO()):
            return audit_guard.main([
                "--audits", str(tmp / "audits"),
                "--baseline", str(tmp / "baseline.json"),
                "--target", str(tmp / "target.toml"),
                *extra,
            ])

    def test_a_clean_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.write(tmp, report_doc(suite("smoke", 1.0)),
                       baseline_doc(suite("smoke", 1.0)), "[suites.smoke]\nenabled = true\n")
            self.assertEqual(self.invoke(tmp), EXIT_OK)

    def test_a_regression_exits_one(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.write(tmp, report_doc(suite("smoke", 0.5)),
                       baseline_doc(suite("smoke", 1.0)), "[suites.smoke]\nenabled = true\n")
            self.assertEqual(self.invoke(tmp), EXIT_FINDINGS)

    def test_no_report_is_a_failure_to_run_not_a_pass(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            (tmp / "audits").mkdir()
            (tmp / "baseline.json").write_text(json.dumps(baseline_doc()))
            (tmp / "target.toml").write_text("")
            self.assertEqual(self.invoke(tmp), EXIT_CANNOT_RUN)

    def test_a_missing_baseline_is_a_failure_to_run(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            (tmp / "audits" / "run").mkdir(parents=True)
            (tmp / "audits" / "run" / "report.json").write_text(
                json.dumps(report_doc(suite("smoke", 1.0))))
            (tmp / "target.toml").write_text("")
            self.assertEqual(self.invoke(tmp), EXIT_CANNOT_RUN)

    def test_it_runs_as_a_script_and_says_which_report_it_read(self):
        result = subprocess.run(
            ["python3", str(GUARD), "--help"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertIn("--summary-file", result.stdout)

    def test_the_summary_file_gets_the_findings_as_markdown(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.write(
                tmp, report_doc(suite("smoke", 0.5)), baseline_doc(suite("smoke", 1.0)),
                "[suites.multilingual]\nenabled = false\ngap = \"g\"\n"
                "fix_belongs_in = \"plumbline\"\n[suites.smoke]\nenabled = true\n",
            )
            summary = tmp / "summary.md"
            code = self.invoke(tmp, "--summary-file", str(summary))
            self.assertEqual(code, EXIT_FINDINGS)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("Cairn audit guard", text)
            self.assertIn("multilingual", text)
            self.assertIn("**regression**", text)


class TestTheGuardIsWiredIntoTheGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.active = "\n".join(
            line for line in cls.text.splitlines() if not line.lstrip().startswith("#")
        )

    def test_the_audit_job_runs_the_guard_after_the_gate(self):
        audit = self.active.split("audit:", 1)[1]
        self.assertIn("audit_guard.py", audit)
        self.assertLess(
            audit.index("plumbline-gate.sh"), audit.index("audit_guard.py"),
            "the guard reads the report the gate writes, so it runs after it",
        )

    def test_the_guard_cannot_be_softened(self):
        audit = self.active.split("audit:", 1)[1]
        guard_step = audit.split("audit_guard.py", 1)[0].rsplit("- name:", 1)[1]
        self.assertNotIn("continue-on-error", guard_step)


if __name__ == "__main__":
    unittest.main()
