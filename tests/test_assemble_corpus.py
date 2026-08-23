"""`assemble_corpus.py`: layers into the one flat directory `cairn index`
reads. Offline; the end-to-end case indexes the assembled directory with
the real engine and asks it a question."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import assemble_corpus
from cairn.config import load_config
from cairn.engine import ask
from cairn.index import build_and_write, read_index

PILOT = """
[layers]
shared = ["federal", "california"]

[counties.los-angeles]
name = "Los Angeles County"
contact = "LA County DPSS at 866-613-3777"

[counties.fresno]
name = "Fresno County"
contact = "Fresno County DSS at 855-832-8082"
"""

TEMPLATE = """
[corpus]
path = "{{CORPUS_PATH}}"

[index]
path = "{{INDEX_PATH}}"

[refusal]
contact = "{{CONTACT}}"
"""


def _doc(doc_id: str, title: str, body: str, *, unreviewed: bool = False) -> str:
    marker = "review: unreviewed\n" if unreviewed else ""
    head = f"---\nid: {doc_id}\ntitle: {title}\nlang: en\nsynthetic: false\n"
    return f"{head}{marker}---\n{body}\n"


def _pilot(tmp: str, *, unreviewed_county_doc: bool = False) -> Path:
    root = Path(tmp) / "pilot"
    layers = root / "layers"
    for layer in ("federal", "california", "los-angeles", "fresno"):
        (layers / layer).mkdir(parents=True)
    (root / "pilot.toml").write_text(PILOT, encoding="utf-8")
    (root / "cairn.template.toml").write_text(TEMPLATE, encoding="utf-8")
    (layers / "federal" / "snap.md").write_text(
        _doc("snap-en", "SNAP", "SNAP helps households buy groceries each month."),
        encoding="utf-8",
    )
    (layers / "california" / "calfresh.md").write_text(
        _doc("calfresh-en", "CalFresh", "CalFresh is California's name for the SNAP program."),
        encoding="utf-8",
    )
    (layers / "california" / "tables").mkdir()
    (layers / "california" / "tables" / "limits.csv").write_text(
        "# id: calfresh-limits-en\n# title: CalFresh income limits\n# lang: en\n"
        "# synthetic: false\nhousehold_size,gross_monthly_limit_usd\n1,2510\n2,3407\n",
        encoding="utf-8",
    )
    (layers / "los-angeles" / "dpss.md").write_text(
        _doc(
            "la-dpss-calfresh-en",
            "Apply for CalFresh in Los Angeles County",
            "Los Angeles County residents apply for CalFresh at a DPSS district office.",
            unreviewed=unreviewed_county_doc,
        ),
        encoding="utf-8",
    )
    (layers / "fresno" / "dss.md").write_text(
        _doc(
            "fresno-dss-calfresh-en",
            "Apply for CalFresh in Fresno County",
            "Fresno County residents apply for CalFresh through the Department of Social "
            "Services.",
        ),
        encoding="utf-8",
    )
    return root


class TestLoadPilot(unittest.TestCase):
    def test_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
        self.assertEqual(pilot.shared, ("federal", "california"))
        self.assertEqual(sorted(pilot.counties), ["fresno", "los-angeles"])
        self.assertIn("866-613-3777", pilot.counties["los-angeles"].contact)

    def test_a_county_without_a_contact_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            (root / "pilot.toml").write_text(
                PILOT.replace('contact = "Fresno County DSS at 855-832-8082"\n', ""),
                encoding="utf-8",
            )
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.load_pilot(root)
        self.assertIn("fresno", str(ctx.exception))
        self.assertIn("contact", str(ctx.exception))

    def test_a_declared_shared_layer_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            (root / "pilot.toml").write_text(
                PILOT.replace('"california"', '"california", "tribal"'), encoding="utf-8"
            )
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.load_pilot(root)
        self.assertIn("tribal", str(ctx.exception))


class TestIsUnreviewed(unittest.TestCase):
    def test_marker_detected_only_inside_front_matter(self):
        with tempfile.TemporaryDirectory() as tmp:
            marked = Path(tmp) / "a.md"
            marked.write_text(_doc("a", "A", "body", unreviewed=True), encoding="utf-8")
            clean = Path(tmp) / "b.md"
            clean.write_text(_doc("b", "B", "review: unreviewed in the body is text"))
            self.assertTrue(assemble_corpus.is_unreviewed(marked))
            self.assertFalse(assemble_corpus.is_unreviewed(clean))


class TestAssemble(unittest.TestCase):
    def test_per_county_holds_shared_layers_plus_that_county_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
            out = Path(tmp) / "la"
            docs, tables = assemble_corpus.assemble(
                pilot, out, county="los-angeles", combined=False
            )
            self.assertEqual((docs, tables), (3, 1))
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(
                names,
                ["cairn.toml", "calfresh.md", "dpss.md", "layers.json", "snap.md", "tables"],
            )
            self.assertFalse((out / "dss.md").exists())  # Fresno's page is not here
            self.assertTrue((out / "tables" / "limits.csv").is_file())
            layers = json.loads((out / "layers.json").read_text(encoding="utf-8"))
            self.assertEqual(layers["layers"], ["federal", "california", "los-angeles"])
            self.assertEqual(
                layers["documents"],
                {
                    "snap-en": "federal",
                    "calfresh-en": "california",
                    "calfresh-limits-en": "california",
                    "la-dpss-calfresh-en": "los-angeles",
                },
            )
            config = (out / "cairn.toml").read_text(encoding="utf-8")
            self.assertIn("866-613-3777", config)
            self.assertNotIn("{{", config)

    def test_combined_holds_every_county_and_says_it_is_not_a_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
            out = Path(tmp) / "all"
            docs, _ = assemble_corpus.assemble(pilot, out, county=None, combined=True)
            self.assertEqual(docs, 4)
            self.assertTrue((out / "dss.md").exists())
            self.assertTrue((out / "dpss.md").exists())
            config = (out / "cairn.toml").read_text(encoding="utf-8")
            self.assertIn("measurement arm, not a deployment", config)
            self.assertIn("Fresno County", config)

    def test_unreviewed_scaffold_blocks_assembly_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp, unreviewed_county_doc=True))
            out = Path(tmp) / "la"
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.assemble(pilot, out, county="los-angeles", combined=False)
            self.assertIn("review: unreviewed", str(ctx.exception))
            self.assertFalse(out.exists())
            # The override exists for smoke runs, and says so.
            docs, _ = assemble_corpus.assemble(
                pilot, out, county="los-angeles", combined=False, allow_unreviewed=True
            )
            self.assertEqual(docs, 3)

    def test_duplicate_ids_across_layers_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            (root / "layers" / "los-angeles" / "dup.md").write_text(
                _doc("snap-en", "A second SNAP", "Duplicate id."), encoding="utf-8"
            )
            pilot = assemble_corpus.load_pilot(root)
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.assemble(
                    pilot, Path(tmp) / "la", county="los-angeles", combined=False
                )
            self.assertIn("snap-en", str(ctx.exception))
            self.assertIn("also declared", str(ctx.exception))

    def test_unknown_county_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.assemble(
                    pilot, Path(tmp) / "x", county="alpine", combined=False
                )
            self.assertIn("alpine", str(ctx.exception))
            self.assertIn("fresno, los-angeles", str(ctx.exception))

    def test_template_missing_a_placeholder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            (root / "cairn.template.toml").write_text(
                TEMPLATE.replace("{{CONTACT}}", "a default nobody should ship"),
                encoding="utf-8",
            )
            pilot = assemble_corpus.load_pilot(root)
            with self.assertRaises(assemble_corpus.AssembleError) as ctx:
                assemble_corpus.assemble(
                    pilot, Path(tmp) / "la", county="los-angeles", combined=False
                )
            self.assertIn("{{CONTACT}}", str(ctx.exception))

    def test_reassembly_replaces_the_previous_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
            out = Path(tmp) / "x"
            assemble_corpus.assemble(pilot, out, county="fresno", combined=False)
            self.assertTrue((out / "dss.md").exists())
            assemble_corpus.assemble(pilot, out, county="los-angeles", combined=False)
            self.assertFalse((out / "dss.md").exists())
            self.assertTrue((out / "dpss.md").exists())


class TestEmptyLayer(unittest.TestCase):
    def test_an_empty_county_layer_warns_and_assembles_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            (root / "layers" / "los-angeles" / "dpss.md").unlink()
            pilot = assemble_corpus.load_pilot(root)
            warnings: list[str] = []
            docs, _ = assemble_corpus.assemble(
                pilot, Path(tmp) / "la", county="los-angeles", combined=False,
                warn=warnings.append,
            )
            self.assertEqual(docs, 2)
            self.assertEqual(len(warnings), 1)
            self.assertIn("los-angeles", warnings[0])
            layers = json.loads((Path(tmp) / "la" / "layers.json").read_text(encoding="utf-8"))
            self.assertEqual(layers["layers"], ["federal", "california", "los-angeles"])
            self.assertNotIn("los-angeles", layers["documents"].values())


class TestEndToEnd(unittest.TestCase):
    def test_the_assembled_corpus_indexes_and_answers_through_the_real_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = assemble_corpus.load_pilot(_pilot(tmp))
            out = Path(tmp) / "la"
            assemble_corpus.assemble(pilot, out, county="los-angeles", combined=False)
            config = load_config(out / "cairn.toml")
            self.assertEqual(Path(config.corpus_path), out)
            build_and_write(config.corpus_path, config.index_path)
            index = read_index(config.index_path, config.corpus_path)
            self.assertEqual(
                sorted({p.doc_id for p in index.passages}),
                ["calfresh-en", "la-dpss-calfresh-en", "snap-en"],
            )
            self.assertEqual(len(index.tables), 1)
            result = ask(
                "Where do Los Angeles County residents apply for CalFresh?", index, config
            )
            self.assertEqual(result.answer.kind, "grounded")
            self.assertEqual(
                result.answer.sources[0].source_id.split("#")[0], "la-dpss-calfresh-en"
            )
            refusal = ask("What vaccinations does my dog need?", index, config)
            self.assertEqual(refusal.answer.kind, "refusal")
            self.assertIn("866-613-3777", refusal.answer.text)


class TestMain(unittest.TestCase):
    def test_cli_error_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = assemble_corpus.main([tmp, "-o", str(Path(tmp) / "x"), "--county", "la"])
            self.assertEqual(code, 1)
            self.assertIn("no pilot.toml", err.getvalue())

    def test_cli_success_names_the_next_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _pilot(tmp)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = assemble_corpus.main(
                    [str(root), "-o", str(Path(tmp) / "la"), "--county", "los-angeles"]
                )
            self.assertEqual(code, 0)
            self.assertIn("3 document(s), 1 table(s)", out.getvalue())
            self.assertIn("cairn --config", out.getvalue())


if __name__ == "__main__":
    unittest.main()
