"""Both limits are enforced by the gate now, so this file guards the wording.

For most of this repository's history `pyproject.toml` configured a complexity
limit of 10, left `C90` out of ruff's `select` because functions were over it,
and said so in a comment. That is the honest handling of a gap, and it depends
entirely on the description being true.

It was not. The comment named eight functions, one by one, with a number each,
and said "the numbers here are the bar that refactor is aiming at". Ruff
reported twelve. Four arrived with the pilot tooling in sessions 17 and 18 -
`assemble_corpus.py`'s `plan`, `import_corpus.py`'s `handle_starttag`,
`handle_endtag` and `scaffold_one` - and nobody recomputed a list that is only
ever recomputed by hand. The README's Code Quality row inherited the same
eight.

This is the defect this repository already knew about in another place. Its
own test for the published test count says it: a claim "was updated by hand
each time somebody remembered, which means a commit that deletes forty tests
can leave the sentence standing and read as a commit that deleted nothing."
The same sentence works here with "adds four complex functions" in the middle.

So the inventory moved out of the comment and into a table a test held to what
ruff actually reported. Twelve, then five, then zero, over 2026-08-27. At zero
the table is not the guard any more: `C90` is in `select`, so a thirteenth
complex function fails the lint step rather than joining a list, and the rule
is stricter than any inventory could be.

`OVER_THE_LIMIT` stays, empty, rather than being deleted with the tests around
it. Emptiness is the claim now, and an empty table that ruff is checked
against says "nothing is over the limit" in a way that deleting the file
cannot. `test_the_rule_is_enforced_rather_than_inventoried` is what would have
to be rewritten to put the gap back, which is the right amount of friction for
a change that would be reintroducing one.

`mypy` is here for the same reason, one line down: strict mode reports zero on
`cairn/` and `make verify` runs it, so what needs holding is that the
configuration still says so and that no module has been excused.
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
# It held twelve when it was written, then five, and now none: `C90` is in
# ruff's `select`, so ruff itself refuses a thirteenth rather than this table
# recording one. Kept empty rather than deleted, because "nothing is over the
# limit" is a claim, and a claim wants something checking it.
OVER_THE_LIMIT: dict[tuple[str, str], int] = {}

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
        # ruff prints native separators, so the same file is `cairn/lint.py`
        # on POSIX and `cairn\\lint.py` on Windows. The inventory is written
        # one way, so normalise here rather than recording two spellings of
        # every entry; without this the test fails on Windows CI only, which
        # is a test that reports a defect the tree does not have.
        path = location.split(":")[0].replace("\\", "/")
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

    def test_the_rule_is_enforced_rather_than_inventoried(self):
        """`C90` in `select` is what makes the emptiness above hold.

        Without it, `make verify` would pass on a tree with a
        thirteenth complex function in it and only this file would
        notice, which is the arrangement that let the count sit at eight
        while ruff said twelve.
        """
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f"max-complexity = {MAX_COMPLEXITY}", text)
        self.assertIn('"C90"', text, "C90 is no longer in ruff's select")
        self.assertFalse(
            OVER_THE_LIMIT,
            "the rule is enforced, so nothing can be over the limit; if "
            "something is, ruff has been switched off rather than the code "
            "fixed",
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
