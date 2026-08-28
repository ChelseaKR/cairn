"""The two configured-but-unenforced limits are described accurately.

`pyproject.toml` configures a complexity limit of 10 and deliberately leaves
`C90` out of ruff's `select`, because functions are over it. That is the
honest handling of a gap, and it depends entirely on the description being
true.

It was not. The comment named eight functions, one by one, with a number
each, and said "the numbers here are the bar that refactor is aiming at". Ruff
reported twelve. Four arrived with the pilot tooling in sessions 17 and 18 -
`assemble_corpus.py`'s `plan`, `import_corpus.py`'s `handle_starttag`,
`handle_endtag` and `scaffold_one` - and nobody recomputed a list that is only
ever recomputed by hand. The README's Code Quality row inherited the same
eight.

This is the defect this repository already knows about in another place. Its
own test for the published test count says it: a claim "was updated by hand
each time somebody remembered, which means a commit that deletes forty tests
can leave the sentence standing and read as a commit that deleted nothing."
The same sentence works here with "adds four complex functions" in the middle.

So the inventory moved out of the comment and into `OVER_THE_LIMIT` below,
where a test holds it to what ruff actually reports, and `pyproject.toml` and
the README now cite the count instead of listing the members. Reducing a
function past the limit fails this test until the entry comes out, which is
the direction the gap is supposed to move; adding a complex function fails it
until somebody writes the entry, which is the moment to notice.

`mypy` needs no equivalent, and did until this file was written. Strict mode
reports zero on `cairn/` now, so `make verify` runs it strictly and the gate
itself is the guard. A number in prose only needs a test when nothing else
holds it.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every function ruff reports over the configured complexity limit, with the
# number it reports. Kept here rather than in `pyproject.toml`'s comment
# because a list nothing checks is a list that goes stale, and this one did.
#
# Four of these have issues of their own; the rest are named here and nowhere
# else. See docs/roadmap.md, phases 3 and 4, for what closing them is worth
# and why the two large ones are not the same task as the small ones.
OVER_THE_LIMIT = {
    ("assemble_corpus.py", "plan"): 12,
    ("audit_guard.py", "harness_defaults"): 11,
    ("audit_guard.py", "regression_findings"): 11,
    ("audit_guard.py", "render_terminal"): 11,
    ("cairn/lint.py", "lint_corpus"): 11,
    ("cairn/server.py", "build_handler"): 56,
    ("cairn/server.py", "_handle_ask"): 19,
    ("cairn/session.py", "_retry_with_context"): 18,
    ("cairn/tabular.py", "parse_count_query"): 11,
    ("import_corpus.py", "handle_starttag"): 18,
    ("import_corpus.py", "handle_endtag"): 20,
    ("import_corpus.py", "scaffold_one"): 11,
}

MAX_COMPLEXITY = 10


def _reported() -> dict[tuple[str, str], int]:
    """What ruff says today, as {(path, function): complexity}.

    Run with `C901` selected explicitly and the limit passed on the command
    line, which is exactly how the issues tell a contributor to check their
    own work. Reading the limit out of `pyproject.toml` instead would make
    this test agree with a configuration that had been edited to make it
    agree.
    """
    result = subprocess.run(
        [
            "ruff", "check",
            "--select", "C901",
            "--config", f"lint.mccabe.max-complexity={MAX_COMPLEXITY}",
            "--output-format", "concise",
            ".",
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    found = {}
    for line in result.stdout.splitlines():
        if "C901" not in line:
            continue
        location, _, message = line.partition(": C901 ")
        path = location.split(":")[0]
        name = message.split("`")[1]
        complexity = int(message.rsplit("(", 1)[1].split(" ")[0])
        found[(path, name)] = complexity
    return found


@unittest.skipIf(
    shutil.which("ruff") is None,
    "ruff is not on PATH; `make verify` puts it there and CI runs that",
)
class TestThePublishedComplexityGapIsTheGap(unittest.TestCase):
    def test_the_inventory_is_exactly_what_ruff_reports(self):
        self.assertEqual(
            _reported(),
            OVER_THE_LIMIT,
            "the recorded inventory of functions over the complexity limit no "
            "longer matches what ruff reports: add the new one, or remove the "
            "one that was fixed, and move the count in pyproject.toml and the "
            "README's Code Quality row with it",
        )

    def test_pyproject_publishes_the_count_and_not_a_hand_kept_list(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f"max-complexity = {MAX_COMPLEXITY}", text)
        self.assertIn(f"{len(OVER_THE_LIMIT)} functions are over it", text)

    def test_the_readme_publishes_the_same_count(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"{len(OVER_THE_LIMIT)} functions are over it", text)

    def test_turning_the_rule_on_is_still_a_refactor(self):
        """The reason `C90` is out of `select`, stated as a fact rather than
        left as a claim: there is something for it to catch. If this ever
        fails, the gap is closed and the rule can simply be switched on."""
        self.assertTrue(
            OVER_THE_LIMIT,
            "nothing is over the limit any more: add C90 to pyproject.toml's "
            "select, delete this inventory, and delete this test",
        )


class TestTheMypyGapIsClosedAndEnforced(unittest.TestCase):
    """`make verify` runs strict mode, so nothing here re-runs mypy.

    What is worth holding is that the configuration says so, because the
    README and CONTRIBUTING both describe the gate and both used to describe
    a gap that no longer exists.
    """

    def test_the_configuration_runs_strict(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("strict = true", text)

    def test_no_module_is_excused_from_it(self):
        """A per-module override is how a strict gate becomes a strict-looking
        gate. CONTRIBUTING's rule was already that silencing a finding with a
        blanket ignore is not welcome; this is that rule, mechanically."""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("[[tool.mypy.overrides]]", text)


if __name__ == "__main__":
    unittest.main()
