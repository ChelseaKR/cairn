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

    def test_a_score_that_rose_also_fails_until_the_baseline_catches_up(self):
        # The ratchet used to work one way: a fall failed, a rise printed a
        # note. Leave the note unactioned and the recorded bar stays at the old
        # number, so every point of the improvement can be given back later
        # and the comparison calls it unchanged. Both directions stop the
        # build now; neither is adopted automatically.
        before = baseline_doc(suite("accuracy", 0.40))
        now = report_doc(suite("accuracy", 0.44))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), ["accuracy"])
        self.assertIn("0.4000 -> 0.4400", findings[0].detail)

    def test_a_rise_and_a_fall_are_not_reported_with_the_same_word(self):
        # Both block; they do not mean the same thing, and a log that called
        # an improvement a regression would teach a reader to skim the word.
        rose = regression_findings(
            report_doc(suite("accuracy", 0.44)), baseline_doc(suite("accuracy", 0.40))
        )
        fell = regression_findings(
            report_doc(suite("accuracy", 0.36)), baseline_doc(suite("accuracy", 0.40))
        )
        self.assertEqual(rose[0].label, "IMPROVEMENT")
        self.assertEqual(fell[0].label, "REGRESSION")

    def test_the_guard_never_adopts_a_number_by_itself(self):
        # The one thing that must not happen in either direction: the file on
        # disk is the bar, and only a person edits it.
        before = baseline_doc(suite("accuracy", 0.40))
        digest = json.dumps(before, sort_keys=True)
        regression_findings(report_doc(suite("accuracy", 0.44)), before)
        regression_findings(report_doc(suite("accuracy", 0.36)), before)
        self.assertEqual(json.dumps(before, sort_keys=True), digest)

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

    def test_a_suite_scored_with_no_baseline_entry_fails(self):
        # A newly enabled suite with nothing recorded for it is a check with
        # no bar under it: it can decay all the way to its floor and this
        # comparison has nothing to say. Same principle as the rise above.
        before = baseline_doc(suite("smoke", 1.0))
        now = report_doc(suite("smoke", 1.0), suite("multilingual", 0.97))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), ["multilingual"])
        self.assertEqual(findings[0].label, "UNPINNED")


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
        # with no bar under it. The guard fails on that at gate time; this
        # catches it offline, before anyone needs the network.
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

    def test_a_gap_that_closed_is_not_still_advertised(self):
        # The mirror of the test below, and the same defect class. A document
        # that still says a suite is unscored after it was switched on is
        # drift, exactly as a document that never said so while it was off.
        # Written as a claim about the present tense, so the historical
        # account of how the gap closed is free to stay.
        # Per suite, not all-or-nothing. The guard used to skip this whole
        # test the moment *any* suite was gapped, but the claim is about each
        # suite separately: one legitimately disabled suite would have let a
        # stale "the multilingual suite is not scored" stand in DESIGN.md
        # forever, with the skip reading as green in the runner's output.
        gaps, _ = declared_gaps(self.target)
        gapped = {gap["suite"] for gap in gaps}
        scored = {entry["suite"] for entry in self.baseline["suites"]} - gapped
        self.assertTrue(scored, "no suite is scored at all; nothing here is checking anything")
        for name in ("README.md", "DESIGN.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for para in text.split("\n\n"):
                for suite_id in scored:
                    if suite_id in para and "is not scored" in para:
                        self.fail(
                            f"{name} still says the {suite_id} suite is not scored, "
                            f"but it is in the committed baseline"
                        )

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


class TestFloorsAndTheSuiteUniverse(unittest.TestCase):
    """A floor is how strict the gate is, so moving one has to be explained;
    and the list of suites has to come from somewhere other than the file
    being audited."""

    DEFAULTS = {"smoke": 1.0, "accuracy": 0.75, "fairness": 0.85}

    def test_a_floor_at_the_default_needs_no_reason(self):
        overrides, findings = audit_guard.floor_findings(
            {"suites": {"fairness": {"enabled": True, "floor": 0.85}}}, self.DEFAULTS
        )
        self.assertEqual(findings, [])
        self.assertEqual(overrides, [])

    def test_an_omitted_floor_is_the_default_and_needs_no_reason(self):
        _, findings = audit_guard.floor_findings(
            {"suites": {"fairness": {"enabled": True}}}, self.DEFAULTS
        )
        self.assertEqual(findings, [])

    def test_a_looser_floor_with_no_reason_fails(self):
        # The case that was live in this repository: fairness at 0.80 against
        # a harness default of 0.85, with nothing on record saying why.
        _, findings = audit_guard.floor_findings(
            {"suites": {"fairness": {"enabled": True, "floor": 0.80}}}, self.DEFAULTS
        )
        self.assertEqual(blocking(findings), ["fairness"])
        self.assertIn("LOOSER", findings[0].detail)

    def test_a_stricter_floor_with_no_reason_fails_too(self):
        # Not because stricter is wrong, but because a gate whose strictness
        # nobody wrote down cannot be reviewed in either direction.
        _, findings = audit_guard.floor_findings(
            {"suites": {"accuracy": {"enabled": True, "floor": 0.95}}}, self.DEFAULTS
        )
        self.assertEqual(blocking(findings), ["accuracy"])

    def test_a_reason_makes_it_a_recorded_override(self):
        overrides, findings = audit_guard.floor_findings(
            {"suites": {"accuracy": {"enabled": True, "floor": 0.35,
                                     "floor_reason": "the metric is wrong for us"}}},
            self.DEFAULTS,
        )
        self.assertEqual(findings, [])
        self.assertEqual(overrides[0]["default"], 0.75)
        self.assertEqual(overrides[0]["floor"], 0.35)

    def test_whitespace_is_not_a_reason(self):
        _, findings = audit_guard.floor_findings(
            {"suites": {"accuracy": {"enabled": True, "floor": 0.35, "floor_reason": "  "}}},
            self.DEFAULTS,
        )
        self.assertEqual(blocking(findings), ["accuracy"])

    def test_a_deleted_suite_is_a_finding_rather_than_a_smaller_universe(self):
        # Delete [suites.privacy] from the config and its line from the
        # baseline in one commit and every other check here agrees, because
        # every other check reads the list of suites out of those two files.
        findings = audit_guard.unmentioned_suites(
            {"suites": {"smoke": {"enabled": True}, "accuracy": {"enabled": True}}},
            self.DEFAULTS,
        )
        self.assertEqual(blocking(findings), ["fairness"])

    def test_a_suite_disabled_with_a_gap_still_counts_as_mentioned(self):
        findings = audit_guard.unmentioned_suites(
            {"suites": {name: {"enabled": True} for name in self.DEFAULTS}}, self.DEFAULTS
        )
        self.assertEqual(findings, [])

    def test_a_gap_declaration_on_a_running_suite_is_a_loaded_gun(self):
        # It would satisfy "a disabled suite must declare a gap" the instant
        # somebody wrote `enabled = false`, using a sentence about a gap that
        # had already closed.
        _, findings = declared_gaps(
            {"suites": {"multilingual": {"enabled": True, "gap": "closed in Aug",
                                         "fix_belongs_in": "plumbline"}}}
        )
        self.assertEqual(blocking(findings), ["multilingual"])

    def test_an_empty_harness_is_an_error_not_an_empty_rulebook(self):
        with tempfile.TemporaryDirectory() as name:
            src = Path(name) / "src"
            (src / "plumbline" / "suites").mkdir(parents=True)
            with self.assertRaises(audit_guard.GuardError):
                audit_guard.harness_defaults(src)
            with self.assertRaises(audit_guard.GuardError):
                audit_guard.harness_defaults(Path(name) / "nothing-here")

    def test_the_committed_config_holds_the_rule_against_the_pinned_harness(self):
        # The real files, when there is a resolved harness to hold them
        # against. This is the guard's job in CI and it runs there; locally it
        # runs whenever ./plumbline-gate.sh has been run at least once. The
        # absence of a harness is reported rather than passed over — see the
        # exit-4 tests above — so this is not a silent skip.
        src = audit_guard.pinned_harness_src(PIN, ROOT / ".plumbline-cache")
        if not (src / "plumbline" / "suites").is_dir():
            self.skipTest("no resolved harness; ./plumbline-gate.sh fetches it")
        defaults = audit_guard.harness_defaults(src)
        target = tomllib.loads(TARGET.read_text(encoding="utf-8"))
        overrides, findings = audit_guard.floor_findings(target, defaults)
        self.assertEqual(blocking(findings), [])
        self.assertEqual(audit_guard.unmentioned_suites(target, defaults), [])
        self.assertTrue(overrides, "this repository does override floors; say which")


class TestRunningIt(unittest.TestCase):
    """End-to-end exits. The floor rule and the missing-suite rule are pure
    functions with their own tests below; here the stand-in harness agrees
    with the target so that these cases exercise the baseline comparison and
    nothing else."""

    def write(self, tmp: Path, report: dict, baseline: dict, target: str,
              harness: dict[str, float] | None = None) -> None:
        (tmp / "audits" / "run").mkdir(parents=True)
        (tmp / "audits" / "run" / "report.json").write_text(json.dumps(report))
        (tmp / "baseline.json").write_text(json.dumps(baseline))
        (tmp / "target.toml").write_text(target, encoding="utf-8")
        # The guard reads default floors out of the pinned harness's source
        # rather than out of Cairn's own config, so running it needs a
        # harness. The core dev path has none on purpose, which is why this
        # writes a minimal stand-in instead of reaching into .plumbline-cache.
        if harness is None:
            parsed = tomllib.loads(target)
            harness = {
                name: float(spec.get("floor", 1.0))
                for name, spec in parsed.get("suites", {}).items()
            }
        suites = tmp / "harness" / "plumbline" / "suites"
        suites.mkdir(parents=True, exist_ok=True)
        (suites / "generated.py").write_text(
            "\n\n".join(
                f'class S{n}:\n    id = "{name}"\n    default_floor = {floor}'
                for n, (name, floor) in enumerate(sorted(harness.items()))
            )
            + "\n",
            encoding="utf-8",
        )

    def invoke(self, tmp: Path, *extra: str) -> int:
        # The guard is a build-log tool; its report belongs in a build log,
        # not in the middle of this suite's output.
        with contextlib.redirect_stdout(io.StringIO()):
            return audit_guard.main([
                "--audits", str(tmp / "audits"),
                "--baseline", str(tmp / "baseline.json"),
                "--target", str(tmp / "target.toml"),
                "--harness-src", str(tmp / "harness"),
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

    def test_an_unadopted_improvement_exits_one_too(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.write(tmp, report_doc(suite("accuracy", 0.9)),
                       baseline_doc(suite("accuracy", 0.5)),
                       "[suites.accuracy]\nenabled = true\n")
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

    def test_it_never_writes_the_baseline_in_either_direction(self):
        # DESIGN.md says "a test pins that the guard never writes to the
        # baseline", in the paragraph arguing that both a fall and a rise stop
        # the build and hand a person the same decision. There was no such
        # test. The behaviour was right — nothing in audit_guard.py opens the
        # baseline for writing — and an unpinned claim about a gate is the
        # thing this repository says it does not accept from anybody else.
        for label, score in (("a fall", 0.5), ("a rise", 0.9)):
            with self.subTest(direction=label), tempfile.TemporaryDirectory() as name:
                tmp = Path(name)
                self.write(tmp, report_doc(suite("accuracy", score)),
                           baseline_doc(suite("accuracy", 0.7)),
                           "[suites.accuracy]\nenabled = true\n")
                before = (tmp / "baseline.json").read_bytes()
                self.assertEqual(self.invoke(tmp), EXIT_FINDINGS)
                self.assertEqual(
                    (tmp / "baseline.json").read_bytes(), before,
                    "the guard adopted the new number instead of reporting it",
                )

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
        # The whole step, not the half of it before the `run:` line.
        # `continue-on-error: true` is valid anywhere in a step's mapping and
        # the obvious place to put it is under the command — which is exactly
        # where the old slice stopped looking. tests/test_interlock.py bans
        # the string workflow-wide, so the hole was covered; the test named
        # for it could not see it, which is the worse half of the problem.
        audit = self.active.split("audit:", 1)[1]
        before, marker, after = audit.partition("audit_guard.py")
        self.assertEqual(marker, "audit_guard.py", "the audit job no longer runs the guard")
        guard_step = before.rsplit("- name:", 1)[1] + marker + after.split("- name:", 1)[0]
        self.assertIn("run:", guard_step, "the slice must cover the command, not just its name")
        self.assertNotIn("continue-on-error", guard_step)


class TestCoverage(unittest.TestCase):
    """A score is a fraction, and the baseline records both halves.

    `passage_attribution` is the suite that made this necessary: it can only
    score an item where a wrong paragraph was available to answer from, so its
    denominator is a property of the target's own retrieval. It can collapse
    to two items and report 1.0000 without a single answer having changed.
    """

    def test_a_suite_that_scored_fewer_items_fails(self):
        before = baseline_doc(suite("passage_attribution", 0.9375, n=16))
        now = report_doc(suite("passage_attribution", 1.0, n=2))
        findings = regression_findings(now, before)
        self.assertEqual(blocking(findings), ["passage_attribution",
                                              "passage_attribution"])
        labels = {f.label for f in findings}
        self.assertIn("COVERAGE", labels)
        self.assertIn("IMPROVEMENT", labels)
        detail = next(f.detail for f in findings if f.label == "COVERAGE")
        self.assertIn("scored 2 items", detail)
        self.assertIn("smaller claim", detail)

    def test_a_suite_that_scored_more_items_also_fails(self):
        # Same argument as an unadopted improvement: coverage nobody recorded
        # is coverage that can be lost again unnoticed.
        before = baseline_doc(suite("refusal", 0.96, n=20))
        now = report_doc(suite("refusal", 0.96, n=26))
        findings = regression_findings(now, before)
        self.assertEqual([f.label for f in findings], ["COVERAGE"])
        self.assertIn("More is checked", findings[0].detail)

    def test_an_unchanged_population_says_nothing(self):
        before = baseline_doc(suite("refusal", 0.96, n=26))
        now = report_doc(suite("refusal", 0.96, n=26))
        self.assertEqual(regression_findings(now, before), [])

    def test_what_a_suite_could_not_check_is_printed(self):
        report = report_doc(suite("passage_attribution", 0.9375, n=16))
        report["suites"][0]["details"] = {
            "unverifiable": {
                "count": 3, "eligible": 19, "scored": 16,
                "reasons": {"no_distractor": ["ck-002", "ck-012", "ck-014"]},
                "note": "excluded from the score",
            }
        }
        lines = audit_guard.uncovered(report)
        self.assertEqual(len(lines), 1)
        self.assertIn("scored 16 of 19 eligible", lines[0])
        self.assertIn("no_distractor 3", lines[0])
        self.assertIn("never passed", lines[0])

    def test_a_suite_that_checked_everything_says_nothing(self):
        self.assertEqual(audit_guard.uncovered(report_doc(suite("refusal", 1.0))), [])

    def test_full_coverage_is_stated_rather_than_left_as_an_absence(self):
        # `uncovered()` reads one key out of somebody else's report format. A
        # pin bump that renamed it would switch every coverage line off at
        # once, and printed as nothing at all that is indistinguishable from a
        # run where every suite really did score everything it was handed. So
        # the empty case is a sentence, in both renderers.
        report = report_doc(suite("refusal", 1.0))
        terminal = audit_guard.render_terminal(
            report_path=Path("report.json"), report=report,
            baseline=baseline_doc(suite("refusal", 1.0)), gaps=[], findings=[],
        )
        self.assertIn(
            "every suite scored everything it was handed",
            "\n".join(terminal),
        )
        markdown = audit_guard.render_markdown(report=report, gaps=[], findings=[])
        self.assertIn("Every suite scored everything it was handed", "\n".join(markdown))

    def test_partial_coverage_replaces_that_sentence_rather_than_joining_it(self):
        report = report_doc(suite("passage_attribution", 0.9375, n=16))
        report["suites"][0]["details"] = {
            "unverifiable": {
                "count": 3, "eligible": 19, "scored": 16,
                "reasons": {"no_distractor": ["ck-002", "ck-012", "ck-014"]},
            }
        }
        terminal = "\n".join(audit_guard.render_terminal(
            report_path=Path("report.json"), report=report,
            baseline=baseline_doc(suite("passage_attribution", 0.9375, n=16)),
            gaps=[], findings=[],
        ))
        self.assertIn("scored 16 of 19 eligible", terminal)
        self.assertNotIn("every suite scored everything", terminal)

    def test_the_committed_run_reports_its_own_coverage(self):
        # Not a fixture: the real report the gate last wrote, if there is one.
        # `passage_attribution` holds items out by design, and the guard has to
        # say so beside a passing verdict rather than only in a fixture.
        target = tomllib.loads(TARGET.read_text(encoding="utf-8"))
        self.assertTrue(target["suites"]["passage_attribution"]["enabled"])
        committed = json.loads(BASELINE.read_text(encoding="utf-8"))
        entry = next(s for s in committed["suites"]
                     if s["suite"] == "passage_attribution")
        self.assertLess(entry["n"], 20, "the suite scores a subset, by design")
        self.assertGreaterEqual(entry["score"], target["suites"]
                                ["passage_attribution"]["floor"])


if __name__ == "__main__":
    unittest.main()
