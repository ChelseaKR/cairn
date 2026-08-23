"""The real-corpus pilot at corpus/pilot-usagov/ — six unedited pages from
usa.gov, imported with import_corpus.py and reviewed by hand — stays
answerable. See docs/pilot-usagov.md for what building and calibrating it
found; this only guards against silent rot, so a future edit to the corpus,
the probe file, or the scorer itself does not quietly break the numbers
that page reports.

Not part of the audited evidence path: `plumbline/bundle/` is graded by the
pinned external harness and is what `audit`/`live` in ci.yml hold required.
This corpus is a demonstration, checked here the same offline way `core`
checks everything else.
"""

import unittest
from pathlib import Path

from cairn.calibrate import calibrate, load_probes
from cairn.config import Config
from cairn.index import build_index
from cairn.lint import lint_corpus

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "pilot-usagov"
PROBES = CORPUS / "probes.toml"


class TestThePilotCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(CORPUS)

    def test_all_six_real_pages_load(self):
        doc_ids = {p.doc_id for p in self.index.passages}
        self.assertEqual(
            doc_ids,
            {
                "snap-en", "energy-bills-en", "lifeline-en",
                "section8-en", "wic-en", "snap-es",
            },
        )

    def test_lint_reports_no_errors(self):
        report = lint_corpus(CORPUS)
        self.assertTrue(report.ok, [i.message for i in report.issues if i.severity == "error"])

    def test_every_document_declares_where_it_really_came_from(self):
        # Not a Cairn-recognised key — inert to retrieval, the same way
        # reviewed_at and review are (cairn/corpus.py) — but a real third
        # party's content living in this repository should say, in the
        # file itself, exactly which live page it was a faithful
        # transcription of on the day it was reviewed.
        for path in sorted(CORPUS.glob("*.md")):
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("source: https://www.usa.gov", text)
                self.assertIn("reviewed_at:", text)

    def test_the_shipped_probe_set_still_calibrates_safely(self):
        report = calibrate(self.index, Config(), PROBES)
        self.assertTrue(report.safe, report.misclassified)

    def test_the_probe_file_actually_has_probes_in_both_languages(self):
        probes = load_probes(PROBES)
        langs = {p.get("lang", "en") for p in probes}
        self.assertIn("es", langs, "the pilot's own Spanish page should have a probe")
        self.assertGreaterEqual(len(probes), 10)


if __name__ == "__main__":
    unittest.main()
