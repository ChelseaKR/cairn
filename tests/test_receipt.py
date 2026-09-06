"""Answer receipts and `cairn verify-receipt` (#101).

The four "Done when" clauses of #101 are each a test here. So is the property
the module exists to protect: a corpus edit reports *corpus changed*, never
*answer differs*, because against different source text the comparison was
never made. `TestOutcomesAreDistinct` is that guard — it fails if the five
outcomes are ever collapsed into a pass/fail.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from cairn.answer import Answer, Source
from cairn.cli import main
from cairn.config import Config
from cairn.engine import ask
from cairn.index import build_and_write, read_index
from cairn.receipt import (
    LOCATION_FIELDS,
    RECEIPT_VERSION,
    Receipt,
    ReceiptError,
    Verdict,
    config_digest,
    receipt_for,
    render,
    verify_receipt,
)
from cairn.retrieve import RetrievalTrace

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "corpus" / "demo"
QUESTION = "How much is the grant?"


def _grounded() -> Answer:
    return Answer(
        kind="grounded",
        text="The grant covers up to $3,500.",
        sources=(
            Source(
                title="Harbor Housing Relief Grant",
                source_id="housing-relief-en#2",
                lang="en",
                text="The grant covers up to $3,500.",
            ),
        ),
        trace=RetrievalTrace(query=QUESTION, candidates=(), threshold=0.165),
        lang="en",
    )


def _refusal() -> Answer:
    return Answer(
        kind="refusal",
        text="I do not have a source for that.",
        sources=(),
        trace=RetrievalTrace(query=QUESTION, candidates=(), threshold=0.165),
        lang="en",
    )



def _future_version_payload() -> dict[str, object]:
    """A receipt document that is valid in every respect except its version."""
    payload = receipt_for(
        _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
    ).to_payload()
    payload["receipt_version"] = RECEIPT_VERSION + 1
    # The stated digest was computed at the current version; drop it so the
    # version check, not the digest check, is what rejects the document.
    del payload["digest"]
    return payload


class _Deployment:
    """A demo corpus and index in a scratch directory, cheap to perturb."""

    def __init__(self, stack: contextlib.ExitStack) -> None:
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.corpus = self.root / "corpus"
        shutil.copytree(DEMO, self.corpus)
        self.index_path = self.root / "index.json"
        self.cfg = Config(corpus_path=str(self.corpus), index_path=str(self.index_path))
        self.reindex()

    def reindex(self) -> None:
        build_and_write(self.corpus, self.index_path)

    @property
    def index(self):  # noqa: ANN201 - the Index type is internal to this helper
        return read_index(self.index_path, self.corpus)

    def answer(self, question: str = QUESTION) -> Answer:
        return ask(question, self.index, self.cfg).answer

    def receipt(self, question: str = QUESTION) -> Receipt:
        return receipt_for(
            self.answer(question),
            question=question,
            corpus_fingerprint=self.index.corpus_fingerprint,
            cfg=self.cfg,
        )

    def verify(self, receipt: Receipt, *, cfg: Config | None = None):  # noqa: ANN201
        config = cfg or self.cfg
        index = self.index
        return verify_receipt(
            receipt,
            corpus_fingerprint=index.corpus_fingerprint,
            cfg=config,
            recompute=lambda: ask(receipt.question, index, config, lang=receipt.lang).answer,
        )


class TestReceiptShape(unittest.TestCase):
    def test_a_receipt_is_determined_by_its_contents(self):
        first = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        second = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.receipt_id, first.digest[:12])
        self.assertEqual(len(first.receipt_id), 12)

    def test_a_different_question_is_a_different_receipt(self):
        first = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        second = receipt_for(
            _grounded(), question="something else", corpus_fingerprint="a" * 64, cfg=Config()
        )
        self.assertNotEqual(first.digest, second.digest)

    def test_a_grounded_receipt_hashes_every_cited_passage(self):
        receipt = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        self.assertEqual(len(receipt.citations), 1)
        self.assertEqual(receipt.citations[0].passage_id, "housing-relief-en#2")
        self.assertEqual(len(receipt.citations[0].text_sha256), 64)
        self.assertIsNone(receipt.refusal_reason)

    def test_a_refusal_gets_a_receipt_carrying_its_reason(self):
        receipt = receipt_for(
            _refusal(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        self.assertEqual(receipt.kind, "refusal")
        self.assertEqual(receipt.citations, ())
        self.assertEqual(receipt.refusal_reason, "I do not have a source for that.")

    def test_a_receipt_round_trips_through_its_document(self):
        receipt = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        restored = Receipt.from_payload(json.loads(json.dumps(receipt.to_payload())))
        self.assertEqual(restored, receipt)
        self.assertEqual(restored.digest, receipt.digest)


class TestConfigDigest(unittest.TestCase):
    def test_a_behavioural_change_moves_the_digest(self):
        self.assertNotEqual(config_digest(Config()), config_digest(Config(threshold=0.4)))
        self.assertNotEqual(
            config_digest(Config()), config_digest(Config(tables_enabled=False))
        )
        self.assertNotEqual(config_digest(Config()), config_digest(Config(max_passages=2)))

    def test_moving_a_file_does_not_move_the_digest(self):
        """A relocated index is the same system. `mv` must not read as drift."""
        self.assertEqual(
            config_digest(Config()),
            config_digest(Config(corpus_path="/elsewhere", index_path="/tmp/i.json")),
        )

    def test_only_the_two_location_fields_are_excluded(self):
        """Pin the deny-list, so a behavioural field cannot join it unnoticed.

        The list is a deny-list rather than an allow-list precisely so a new
        `Config` field is covered by default. This test is the other half:
        it fails if anything is added to the exclusion.
        """
        self.assertEqual(LOCATION_FIELDS, frozenset({"corpus_path", "index_path"}))

    def test_every_other_config_field_actually_reaches_the_digest(self):
        """A field silently outside the digest is a receipt that cannot fail.

        Walks every `Config` field that is not a declared location, perturbs
        it, and asserts the digest moves. A field added later and forgotten
        here is caught by construction rather than by review.
        """
        baseline = config_digest(Config())
        perturbations: dict[str, object] = {
            "threshold": 0.4,
            "max_passages": 3,
            "candidates": 5,
            "margin_warn": 0.05,
            "dense_weight": 0.5,
            "split_intents": True,
            "tables_enabled": False,
            "default_lang": "es",
            "cross_language_fallback": False,
            "contact": "someone@example.gov",
            "contact_by_language": {"en": "someone@example.gov"},
        }
        covered = {f.name for f in fields(Config)} - LOCATION_FIELDS
        self.assertEqual(
            set(perturbations), covered, "a Config field has no perturbation here"
        )
        for name, value in perturbations.items():
            with self.subTest(field=name):
                self.assertNotEqual(
                    baseline,
                    config_digest(Config(**{name: value})),
                    f"changing {name} does not move the config digest",
                )


class TestOutcomesAreDistinct(unittest.TestCase):
    """The five outcomes, and the order that makes each of them honest."""

    def test_a_demo_answer_verifies_match(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            verification = deployment.verify(deployment.receipt())
            self.assertIs(verification.verdict, Verdict.MATCH)
            self.assertTrue(verification.ok)

    def test_a_refusal_verifies_match(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            question = "What is the airspeed velocity of an unladen swallow?"
            receipt = deployment.receipt(question)
            self.assertEqual(receipt.kind, "refusal")
            self.assertIs(deployment.verify(receipt).verdict, Verdict.MATCH)

    def test_editing_the_answer_reports_answer_differs(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            payload = deployment.receipt().to_payload()
            payload["answer_sha256"] = "0" * 64
            del payload["digest"]
            tampered = Receipt.from_payload(payload)
            verification = deployment.verify(tampered)
            self.assertIs(verification.verdict, Verdict.ANSWER_DIFFERS)
            self.assertIn("answer text", verification.detail)

    def test_a_corpus_edit_reports_corpus_changed_not_answer_differs(self):
        """#101's load-bearing clause.

        Editing the corpus changes both the fingerprint *and* the answer. A
        verifier that compared answers first would report `answer differs`,
        which reads as "this deployment has drifted" when the truth is "you
        are asking about different text". The corpus check runs first and
        stops.
        """
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            receipt = deployment.receipt()
            before = deployment.index.corpus_fingerprint
            self._edit_the_grant_amount(deployment)
            deployment.reindex()
            # The edit must actually have landed, and must actually have moved
            # both the fingerprint and the answer. A mutation that silently
            # no-ops would let this test pass while proving nothing.
            self.assertNotEqual(before, deployment.index.corpus_fingerprint)
            self.assertNotEqual(
                receipt.answer_sha256, deployment.receipt().answer_sha256
            )

            verification = deployment.verify(receipt)
            self.assertIs(verification.verdict, Verdict.CORPUS_CHANGED)
            self.assertIsNot(verification.verdict, Verdict.ANSWER_DIFFERS)
            self.assertIn("not re-compared", verification.detail)

    @staticmethod
    def _edit_the_grant_amount(deployment: _Deployment) -> None:
        """Change the quoted amount, asserting the substitution really applied."""
        target = deployment.corpus / "housing-relief.en.md"
        original = target.read_text(encoding="utf-8")
        edited = original.replace("$3,500", "$4,000")
        assert edited != original, "the corpus edit did not apply; the test proves nothing"
        target.write_text(edited, encoding="utf-8")

    def test_a_configuration_change_reports_configuration_changed(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            receipt = deployment.receipt()
            other = Config(
                corpus_path=str(deployment.corpus),
                index_path=str(deployment.index_path),
                threshold=0.9,
            )
            verification = deployment.verify(receipt, cfg=other)
            self.assertIs(verification.verdict, Verdict.CONFIGURATION_CHANGED)
            self.assertIn("not re-compared", verification.detail)

    def test_corpus_is_checked_before_configuration(self):
        """Both changed: the report names the corpus, the more basic fact."""
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            receipt = deployment.receipt()
            self._edit_the_grant_amount(deployment)
            deployment.reindex()
            other = Config(
                corpus_path=str(deployment.corpus),
                index_path=str(deployment.index_path),
                threshold=0.9,
            )
            self.assertIs(
                deployment.verify(receipt, cfg=other).verdict, Verdict.CORPUS_CHANGED
            )

    def test_a_relocated_index_still_verifies_match(self):
        """The location-field exclusion, end to end rather than on the digest alone."""
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            receipt = deployment.receipt()
            moved = deployment.root / "moved-index.json"
            shutil.copyfile(deployment.index_path, moved)
            relocated = Config(
                corpus_path=str(deployment.corpus), index_path=str(moved)
            )
            index = read_index(moved, deployment.corpus)
            verification = verify_receipt(
                receipt,
                corpus_fingerprint=index.corpus_fingerprint,
                cfg=relocated,
                recompute=lambda: ask(receipt.question, index, relocated).answer,
            )
            self.assertIs(verification.verdict, Verdict.MATCH)


class TestUnreadableIsNotAMismatch(unittest.TestCase):
    """An unreadable receipt is evidence of nothing, and must never read as
    evidence against the deployment."""

    def test_a_future_version_is_refused_by_name(self):
        """An otherwise-complete receipt, rejected for its version and nothing else.

        A bare `{"receipt_version": 99}` is rejected by *every* field check in
        `from_payload`, so it would pass this test with the version check
        removed entirely. Measured: it did. The document below is valid in
        every other respect, so only the version can reject it.
        """
        payload = _future_version_payload()
        with self.assertRaises(ReceiptError) as caught:
            Receipt.from_payload(payload)
        message = str(caught.exception)
        self.assertIn(str(RECEIPT_VERSION + 1), message)
        self.assertIn("version", message)

        # Proof the document is otherwise sound: at the current version it parses.
        payload["receipt_version"] = RECEIPT_VERSION
        self.assertEqual(Receipt.from_payload(payload).receipt_version, RECEIPT_VERSION)

    def test_a_missing_field_is_refused_rather_than_defaulted(self):
        receipt = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        for key in (
            "cairn_version",
            "corpus_fingerprint",
            "config_digest",
            "question",
            "lang",
            "kind",
            "answer_sha256",
            "citations",
        ):
            with self.subTest(missing=key):
                payload = receipt.to_payload()
                del payload[key]
                del payload["digest"]
                with self.assertRaises(ReceiptError):
                    Receipt.from_payload(payload)

    def test_an_edited_document_that_states_a_stale_digest_is_refused(self):
        """An edit is named as an edit, not surfaced later as `answer differs`."""
        receipt = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        payload = receipt.to_payload()
        payload["question"] = "a question nobody asked"
        with self.assertRaises(ReceiptError) as caught:
            Receipt.from_payload(payload)
        self.assertIn("edited", str(caught.exception))

    def test_a_refusal_receipt_may_not_cite_passages(self):
        receipt = receipt_for(
            _grounded(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        payload = receipt.to_payload()
        payload["kind"] = "refusal"
        payload["refusal_reason"] = "no source"
        del payload["digest"]
        with self.assertRaises(ReceiptError) as caught:
            Receipt.from_payload(payload)
        self.assertIn("cites passages", str(caught.exception))

    def test_a_grounded_receipt_may_not_cite_nothing(self):
        receipt = receipt_for(
            _refusal(), question=QUESTION, corpus_fingerprint="a" * 64, cfg=Config()
        )
        payload = receipt.to_payload()
        payload["kind"] = "grounded"
        payload["refusal_reason"] = None
        del payload["digest"]
        with self.assertRaises(ReceiptError) as caught:
            Receipt.from_payload(payload)
        self.assertIn("cites nothing", str(caught.exception))


class TestCli(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_ask_receipt_out_writes_a_verifiable_document(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            config_path = deployment.root / "cairn.toml"
            config_path.write_text(
                "[corpus]\n"
                f'path = "{deployment.corpus}"\n'
                "[index]\n"
                f'path = "{deployment.index_path}"\n',
                encoding="utf-8",
            )
            receipt_path = deployment.root / "receipt.json"
            code, out, _ = self._run(
                [
                    "--config",
                    str(config_path),
                    "ask",
                    QUESTION,
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("receipt ", out)
            self.assertTrue(receipt_path.is_file())

            code, out, _ = self._run(
                ["--config", str(config_path), "verify-receipt", str(receipt_path)]
            )
            self.assertEqual(code, 0)
            self.assertIn("MATCH", out)

    def test_verify_receipt_exits_2_on_an_unreadable_document(self):
        """Exit 2, not 1: a typo is not a deployment that has drifted."""
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            config_path = deployment.root / "cairn.toml"
            config_path.write_text(
                f'[corpus]\npath = "{deployment.corpus}"\n'
                f'[index]\npath = "{deployment.index_path}"\n',
                encoding="utf-8",
            )
            bad = deployment.root / "bad.json"
            bad.write_text(
                json.dumps(_future_version_payload()), encoding="utf-8"
            )
            code, out, _ = self._run(
                ["--config", str(config_path), "verify-receipt", str(bad)]
            )
            self.assertEqual(code, 2)
            self.assertIn("UNREADABLE", out)

            missing = deployment.root / "absent.json"
            code, _, err = self._run(
                ["--config", str(config_path), "verify-receipt", str(missing)]
            )
            self.assertEqual(code, 2)
            self.assertIn("cannot read", err)

    def test_a_stale_index_refuses_before_the_receipt_is_opened(self):
        """The freshness contract, pinned at this verb's own entry point.

        `verify-receipt` re-asks, so it can quote the corpus, and every command
        that can quote the corpus must refuse a stale index first. The receipt
        path below does not exist: if the index check ran second, this would
        exit 2 with "cannot read" instead of refusing.
        """
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            config_path = deployment.root / "cairn.toml"
            config_path.write_text(
                f'[corpus]\npath = "{deployment.corpus}"\n'
                f'[index]\npath = "{deployment.index_path}"\n',
                encoding="utf-8",
            )
            document = deployment.corpus / "grocery-allowance.en.md"
            document.write_text(
                document.read_text(encoding="utf-8") + "\nAn edit after indexing.\n",
                encoding="utf-8",
            )
            code, out, err = self._run(
                [
                    "--config",
                    str(config_path),
                    "verify-receipt",
                    str(deployment.root / "does-not-exist.json"),
                ]
            )
            self.assertEqual(code, 1)
            self.assertIn("has changed since the index was built", err)
            self.assertNotIn("cannot read", err)
            self.assertEqual(out, "")

    def test_ask_without_the_flag_prints_no_receipt(self):
        """The default path is unchanged: no receipt unless one was asked for."""
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            config_path = deployment.root / "cairn.toml"
            config_path.write_text(
                f'[corpus]\npath = "{deployment.corpus}"\n'
                f'[index]\npath = "{deployment.index_path}"\n',
                encoding="utf-8",
            )
            code, out, _ = self._run(["--config", str(config_path), "ask", QUESTION])
            self.assertEqual(code, 0)
            self.assertNotIn("receipt ", out)

            code, out, _ = self._run(
                ["--config", str(config_path), "ask", QUESTION, "--json"]
            )
            self.assertEqual(code, 0)
            self.assertNotIn("receipt", json.loads(out))

    def test_ask_json_carries_the_receipt_when_asked(self):
        with contextlib.ExitStack() as stack:
            deployment = _Deployment(stack)
            config_path = deployment.root / "cairn.toml"
            config_path.write_text(
                f'[corpus]\npath = "{deployment.corpus}"\n'
                f'[index]\npath = "{deployment.index_path}"\n',
                encoding="utf-8",
            )
            code, out, _ = self._run(
                ["--config", str(config_path), "ask", QUESTION, "--json", "--receipt"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertIn("receipt", payload)
            self.assertEqual(payload["receipt"]["receipt_version"], RECEIPT_VERSION)
            self.assertEqual(len(payload["receipt"]["receipt_id"]), 12)


class TestRendering(unittest.TestCase):
    def test_every_verdict_renders_its_own_name(self):
        """No verdict may render as another's text."""
        seen = set()
        for verdict in Verdict:
            from cairn.receipt import Verification

            text = render(Verification(verdict=verdict, detail="d", receipt_id="abc"))
            self.assertIn(verdict.value.upper(), text)
            seen.add(text.splitlines()[0])
        self.assertEqual(len(seen), len(list(Verdict)))


if __name__ == "__main__":
    unittest.main()
