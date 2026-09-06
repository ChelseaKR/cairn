#!/usr/bin/env python3
"""Write the README's test count from the suite, instead of typing it.

`tests/test_docs.py::test_the_published_test_count_is_the_count` already
derives the true number -- it discovers the suite and compares
`countTestCases()` to the digits in the README's second paragraph -- so the
published figure has been checked for a while. What was never derived is the
*edit*. The gate tells you the sentence is wrong; a person still has to open
README.md and retype it.

That is a mechanical tax, and it is not free. The same line conflicted in
three consecutive pull requests here (#89, #103, #104) and was hand-rebased
three times, each time with a diff whose entire content was a number. Every
branch that adds a test file has to touch the one line every other branch
that adds a test file also touches.

So: one command writes it.

    python3 readme_counts.py            # rewrite README.md from the suite
    python3 readme_counts.py --check    # exit 1 if it would change anything

The count comes from the same `unittest` discovery the gate uses, and
discovery does not run anything -- `countTestCases()` walks the suite the
loader built -- so this cannot recurse and cannot be perturbed by how it was
invoked.

**The browser figures are deliberately not written here.** "63 browser
behaviour checks" is pinned in `tests/browser/a11y.mjs`, which holds itself to
the number at run time, and the README also shows `63/63 behaviour checks
passed` as console output from a real run. Rewriting that second line from a
constant would be inventing output that no browser produced, which is the
exact defect this repository exists to refuse. Those two move together, by
hand, when somebody adds a browser check and re-runs it; `test_docs.py` holds
them equal either way. Only the count that changes on every ordinary pull
request is automated.
"""

from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"

# "947 tests plus". Anchored on `tests plus` rather than on ` tests`, which is
# what the gate's looser regex would find, so that a future sentence
# mentioning some other number of tests cannot silently become the thing this
# rewrites.
CLAIM = re.compile(r"\b(?P<count>\d+)(?= tests plus\b)")


def collected(root: Path = ROOT) -> int:
    """How many tests the suite holds, discovered and not run."""
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    if unittest.defaultTestLoader.errors:  # pragma: no cover - a broken tree
        raise SystemExit(
            "readme_counts: discovery failed, so the count would be an undercount:\n"
            + "\n".join(unittest.defaultTestLoader.errors)
        )
    return suite.countTestCases()


def rewrite(text: str, count: int) -> str:
    """The README with its published test count set to `count`.

    Raises if the sentence is gone: a writer that silently writes nothing is
    the same failure as a gate that silently passes.
    """
    replaced, hits = CLAIM.subn(str(count), text)
    if hits == 0:
        raise SystemExit(
            "readme_counts: README.md no longer says `N tests plus`, so there is "
            "nothing to write. Restore the sentence or update CLAIM here."
        )
    return replaced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing",
    )
    arguments = parser.parse_args(argv)

    count = collected()
    before = README.read_text(encoding="utf-8")
    after = rewrite(before, count)

    if before == after:
        print(f"readme_counts: README.md already publishes {count} tests")
        return 0
    if arguments.check:
        print(
            f"readme_counts: README.md is stale -- the suite holds {count} tests. "
            "Run `make counts` (or `python3 readme_counts.py`).",
            file=sys.stderr,
        )
        return 1
    README.write_text(after, encoding="utf-8")
    print(f"readme_counts: README.md now publishes {count} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
