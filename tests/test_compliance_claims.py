"""The compliance page's retention section, held to the command line it describes.

The page used to say an answer receipt is "handed to the person who asked and
stored nowhere. The deployment keeps no copy, so there is nothing here to
retain, purge, or disclose." `cairn ask --receipt-out PATH` writes the receipt
to `PATH`, and a receipt carries the question verbatim (``cairn/receipt.py``'s
``to_payload``), so a receipt file is the question in a file. The claim was
true of `cairn serve`, which has no receipt surface, and false of the command
line, and the one document a records officer reads said the file could not
exist. `tests/test_receipt.py::test_ask_receipt_out_writes_a_verifiable_document`
had been asserting the opposite since the flag shipped.

Nothing read the sentence, so this reads it. The check is deliberately an
equality against the parser rather than a substring hunt: every PATH-valued
option on the two verbs a member of the public's words can reach is
classified here as one this tool reads or one it writes, and every writing
one must be named in "Records retention". A new PATH option on `ask` or
`serve` fails until somebody says which it is, which is the moment to ask
whether the retention section is still complete.
"""

import argparse
import re
import unittest
from pathlib import Path

from cairn.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
COMPLIANCE = ROOT / "docs" / "compliance.md"

#: PATH-valued options that name a file this tool only ever reads.
READS: frozenset[str] = frozenset({"--compare-config", "--compare-index"})

#: PATH-valued options that name a file this tool writes. Each must be named
#: in the retention section, because each is a file somebody has to keep,
#: purge or disclose.
WRITES: frozenset[str] = frozenset({"--receipt-out", "--refusal-stats", "--followup-store"})


def _path_options(verb: str) -> set[str]:
    """Every ``--option PATH`` on one subcommand, from the parser itself."""
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices[verb]
            return {
                a.option_strings[-1]
                for a in sub._actions
                if a.option_strings and a.metavar == "PATH"
            }
    raise AssertionError("the parser has no subcommands")


def _retention_section() -> str:
    text = COMPLIANCE.read_text(encoding="utf-8")
    start = text.index("\n## Records retention\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


class TestTheRetentionSectionIsComplete(unittest.TestCase):
    def test_every_path_option_on_ask_and_serve_is_classified(self):
        """A floor first: the parser really does expose these options."""
        found = _path_options("ask") | _path_options("serve")
        self.assertTrue(found, "no PATH-valued option found at all, which is not a pass")
        self.assertEqual(
            found,
            READS | WRITES,
            "a PATH-valued option on `ask` or `serve` is neither declared as read nor as "
            "written; classify it, and if it writes, name it in docs/compliance.md's "
            "Records retention section",
        )

    def test_every_writing_option_is_named_in_the_retention_section(self):
        section = _retention_section()
        missing = sorted(option for option in WRITES if option not in section)
        self.assertEqual(
            missing,
            [],
            f"docs/compliance.md's Records retention section does not name {missing}; "
            "each of these writes a file somebody has to retain, purge or disclose",
        )

    def test_the_receipt_bullet_does_not_say_the_file_cannot_exist(self):
        section = _retention_section()
        self.assertNotRegex(
            section,
            re.compile(r"nothing here to retain, purge, or disclose"),
            "the receipt bullet still says there is nothing to retain; --receipt-out "
            "writes a receipt, and a receipt carries the question verbatim",
        )

    def test_a_receipt_payload_really_does_carry_the_question(self):
        """The other direction.

        If receipts stopped carrying the question, the sentence this test
        protects would be overstating the exposure rather than understating
        it, and the three checks above would all still pass.
        """
        from cairn.receipt import _REQUIRED_STRINGS, Receipt

        self.assertIn("question", _REQUIRED_STRINGS)
        self.assertIn("question", {f.name for f in Receipt.__dataclass_fields__.values()})


if __name__ == "__main__":
    unittest.main()
