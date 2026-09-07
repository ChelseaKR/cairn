"""Answer receipts: the determinism claim, made checkable by the asker (#101).

DESIGN.md's promise is that an identical corpus, an identical configuration
and an identical question always yield an identical answer. A receipt turns
that promise into something a resident can hold: a short document naming the
corpus fingerprint, the effective configuration, the question, the language,
the cited passages with their text hashes, and a hash over the answer itself.
``verify-receipt`` re-asks and reports what it found.

Nothing is stored. Verification is recomputation, so the receipt is given to
the asker and the deployment keeps no record of who asked what — the same
no-storage stance the rest of the project takes.

**The outcomes are distinct on purpose, and their order is the design.** When
the corpus fingerprint has moved, the honest report is *corpus changed*: the
answer this deployment gives now is an answer about different source text, and
comparing it to the recorded one would be comparing two different questions.
Reporting that as ``answer differs`` would be the portfolio's dominant defect
— a check that could not run, published as a finding. So a fingerprint
mismatch stops the comparison and says so, and the same is true one step later
for configuration. Only when both match does the answer comparison run and
mean anything.

A receipt this build cannot parse is ``unreadable``, which is a fifth outcome
and not a sixth kind of mismatch: an unreadable receipt is evidence of
nothing, and must never read as evidence against the deployment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any

from cairn import __version__
from cairn.answer import Answer
from cairn.config import Config

__all__ = [
    "LOCATION_FIELDS",
    "RECEIPT_VERSION",
    "Citation",
    "Receipt",
    "ReceiptError",
    "Verification",
    "Verdict",
    "config_digest",
    "receipt_for",
    "verify_receipt",
]

# 2 when the jurisdiction a question was asked about joined the document.
# A version bump rather than an optional field read with `.get`, because a
# build that has never heard of jurisdictions would recompute a receipt
# written for one county against no county at all — and where the two happen
# to give the same text, report MATCH for an answer produced under a
# different scope. A receipt that can say MATCH about a comparison it did not
# make is worse than one this build declines to read.
RECEIPT_VERSION = 2

# `Config` fields that say *where* files are, not *what the system does*.
#
# Held as a deny-list rather than an allow-list, and that is the whole point:
# a new `Config` field is behavioural until somebody deliberately adds it
# here, so a knob added next year is covered by every receipt written before
# anyone thought about receipts. An allow-list would have exactly the opposite
# failure — the new knob silently outside the digest, and a deployment that
# had changed its behaviour verifying MATCH.
#
# `config_report._RATIONALE` already draws this line in the same place, in its
# own words: "`corpus_path` and `index_path` are locations, not tuned values".
# Moving an index file does not change a single word of a single answer, and a
# receipt that reported "configuration changed" for `mv` would train its reader
# to ignore the field that matters.
LOCATION_FIELDS = frozenset({"corpus_path", "index_path"})


class ReceiptError(Exception):
    """A receipt document is missing, malformed, or from an unreadable version."""


class Verdict(StrEnum):
    """What verification found. Five outcomes, none of them a fallback."""

    MATCH = "MATCH"
    CORPUS_CHANGED = "corpus changed"
    CONFIGURATION_CHANGED = "configuration changed"
    ANSWER_DIFFERS = "answer differs"
    UNREADABLE = "unreadable"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    """The one serialization every digest in this module is taken over."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_digest(cfg: Config) -> str:
    """A digest over every behavioural field of ``cfg``.

    Values go through ``repr`` rather than JSON so that ``0.165`` and
    ``"0.165"`` cannot collide, and so a field holding a type JSON has no
    notion of still contributes rather than raising.
    """
    material = {
        f.name: repr(getattr(cfg, f.name))
        for f in fields(Config)
        if f.name not in LOCATION_FIELDS
    }
    return _sha256(_canonical(material))


@dataclass(frozen=True)
class Citation:
    """One cited passage, identified and hashed."""

    passage_id: str
    text_sha256: str

    def to_payload(self) -> dict[str, str]:
        return {"passage_id": self.passage_id, "text_sha256": self.text_sha256}

    @classmethod
    def from_payload(cls, payload: Any) -> Citation:
        if not isinstance(payload, dict):
            raise ReceiptError("a citation entry is not an object")
        passage_id = payload.get("passage_id")
        text_sha256 = payload.get("text_sha256")
        if not isinstance(passage_id, str) or not isinstance(text_sha256, str):
            raise ReceiptError("a citation entry is missing passage_id or text_sha256")
        return cls(passage_id=passage_id, text_sha256=text_sha256)


@dataclass(frozen=True)
class Receipt:
    """What was asked, of which corpus, under which configuration, and what came back."""

    receipt_version: int
    cairn_version: str
    corpus_fingerprint: str
    config_digest: str
    question: str
    lang: str
    # The jurisdiction the question was asked about, or `None` where the
    # deployment is not layered. Part of what was asked, exactly like `lang`,
    # and therefore part of what a verification has to re-ask.
    jurisdiction: str | None
    kind: str  # "grounded" | "refusal"
    answer_sha256: str
    citations: tuple[Citation, ...]
    # The refusal text, for a refusal, and None for a grounded answer. A
    # refusal's text *is* its reason, and it is carried in the clear because
    # the person holding the receipt should be able to read what they were
    # told without recomputing anything.
    refusal_reason: str | None

    @property
    def digest(self) -> str:
        """The hash over everything above — the receipt's identity."""
        return _sha256(_canonical(self._material()))

    @property
    def receipt_id(self) -> str:
        """The short form printed to a person."""
        return self.digest[:12]

    def _material(self) -> dict[str, Any]:
        return {
            "answer_sha256": self.answer_sha256,
            "cairn_version": self.cairn_version,
            "citations": [c.to_payload() for c in self.citations],
            "config_digest": self.config_digest,
            "corpus_fingerprint": self.corpus_fingerprint,
            "jurisdiction": self.jurisdiction,
            "kind": self.kind,
            "lang": self.lang,
            "question": self.question,
            "receipt_version": self.receipt_version,
            "refusal_reason": self.refusal_reason,
        }

    def to_payload(self) -> dict[str, Any]:
        """The document written to disk and shown in `--json`."""
        return {**self._material(), "digest": self.digest, "receipt_id": self.receipt_id}

    @classmethod
    def from_payload(cls, payload: Any) -> Receipt:
        """Parse a receipt document, rejecting anything this build cannot read.

        Raises:
            ReceiptError: the document is not a receipt this build understands.
                It is never repaired into a partial one — a receipt with a
                field guessed at would verify against something nobody wrote.
        """
        if not isinstance(payload, dict):
            raise ReceiptError("receipt is not a JSON object")
        version = payload.get("receipt_version")
        if version != RECEIPT_VERSION:
            raise ReceiptError(
                f"receipt is version {version!r}; this build of cairn reads "
                f"version {RECEIPT_VERSION} only"
            )
        values = _required_strings(payload)
        jurisdiction = _jurisdiction_of(payload)
        citations = _citations_of(payload)
        reason = _refusal_reason_of(payload)
        _check_kind_consistency(values["kind"], citations, reason)
        receipt = cls(
            receipt_version=RECEIPT_VERSION,
            cairn_version=values["cairn_version"],
            corpus_fingerprint=values["corpus_fingerprint"],
            config_digest=values["config_digest"],
            question=values["question"],
            lang=values["lang"],
            jurisdiction=jurisdiction,
            kind=values["kind"],
            answer_sha256=values["answer_sha256"],
            citations=citations,
            refusal_reason=reason,
        )
        _check_stated_digest(payload, receipt)
        return receipt


_REQUIRED_STRINGS = (
    "cairn_version",
    "corpus_fingerprint",
    "config_digest",
    "question",
    "lang",
    "kind",
    "answer_sha256",
)


def _required_strings(payload: dict[str, Any]) -> dict[str, str]:
    """Every field that must be present, non-empty text."""
    values: dict[str, str] = {}
    for key in _REQUIRED_STRINGS:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ReceiptError(f"receipt has no usable {key}")
        values[key] = value
    if values["kind"] not in {"grounded", "refusal"}:
        raise ReceiptError(f"receipt has unknown kind {values['kind']!r}")
    return values


def _jurisdiction_of(payload: dict[str, Any]) -> str | None:
    """The layer asked about: text, or absent.

    Absent and `null` both mean "no layer was in force", which is a real
    state and not a missing field — so this is not in `_REQUIRED_STRINGS`.
    An empty string is refused rather than folded into that: it is a value
    nothing can produce, so a document carrying one has been edited or
    written by something that did not understand the field.
    """
    value = payload.get("jurisdiction")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ReceiptError("receipt jurisdiction is neither a code nor absent")
    return value


def _citations_of(payload: dict[str, Any]) -> tuple[Citation, ...]:
    raw = payload.get("citations")
    if not isinstance(raw, list):
        raise ReceiptError("receipt has no citations list")
    return tuple(Citation.from_payload(entry) for entry in raw)


def _refusal_reason_of(payload: dict[str, Any]) -> str | None:
    reason = payload.get("refusal_reason")
    if reason is not None and not isinstance(reason, str):
        raise ReceiptError("receipt refusal_reason is neither text nor absent")
    return reason


def _check_kind_consistency(
    kind: str, citations: tuple[Citation, ...], reason: str | None
) -> None:
    """The same two-outcome promise `Answer.__post_init__` holds, on paper.

    A receipt is the shape a person keeps, so a document claiming a grounded
    answer that cites nothing — or a refusal that cites a passage — is refused
    here rather than verified into a verdict about a thing that never happened.
    """
    if kind == "refusal":
        if reason is None:
            raise ReceiptError("a refusal receipt carries no refusal reason")
        if citations:
            raise ReceiptError("a refusal receipt cites passages")
        return
    if reason is not None:
        raise ReceiptError("a grounded receipt carries a refusal reason")
    if not citations:
        raise ReceiptError("a grounded receipt cites nothing")


def _check_stated_digest(payload: dict[str, Any], receipt: Receipt) -> None:
    """A `digest` in the document is checked, never trusted.

    It is a convenience for a reader, and a receipt whose stated digest does
    not match its own contents has been edited. Saying so here is better than
    letting the edit surface later as "answer differs", which would blame the
    deployment for a change made to the paper.
    """
    stated = payload.get("digest")
    if stated is None:
        return
    if not isinstance(stated, str):
        raise ReceiptError("receipt digest is not text")
    if stated != receipt.digest:
        raise ReceiptError(
            "receipt digest does not match its own contents: the document "
            "has been edited since it was issued"
        )


def receipt_for(
    answer: Answer,
    *,
    question: str,
    corpus_fingerprint: str,
    cfg: Config,
    jurisdiction: str | None = None,
) -> Receipt:
    """Build the receipt for one answer or refusal."""
    citations = tuple(
        Citation(passage_id=source.source_id, text_sha256=_sha256(source.text))
        for source in answer.sources
    )
    return Receipt(
        receipt_version=RECEIPT_VERSION,
        cairn_version=__version__,
        corpus_fingerprint=corpus_fingerprint,
        config_digest=config_digest(cfg),
        question=question,
        lang=answer.lang,
        jurisdiction=jurisdiction,
        kind=answer.kind,
        answer_sha256=_sha256(answer.text),
        citations=citations,
        refusal_reason=answer.text if answer.kind == "refusal" else None,
    )


@dataclass(frozen=True)
class Verification:
    """The outcome of re-asking, and enough detail to act on it."""

    verdict: Verdict
    detail: str
    receipt_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.MATCH

    def to_payload(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "detail": self.detail,
            "receipt_id": self.receipt_id,
            "match": self.ok,
        }


def verify_receipt(
    receipt: Receipt,
    *,
    corpus_fingerprint: str,
    cfg: Config,
    recompute: Any,
) -> Verification:
    """Re-ask and report which of the five outcomes holds.

    ``recompute`` is a zero-argument callable returning the :class:`Answer`
    this deployment gives for ``receipt.question`` now. It is injected rather
    than imported so this module stays independent of the engine — and so the
    ordering below can be tested without building an index for every case.

    The order is load-bearing. Corpus first, then configuration, then the
    answer: each earlier mismatch makes the later comparison meaningless, and
    a meaningless comparison reported as a finding is worse than no finding.
    """
    if corpus_fingerprint != receipt.corpus_fingerprint:
        return Verification(
            verdict=Verdict.CORPUS_CHANGED,
            detail=(
                f"the corpus is now {corpus_fingerprint[:12]}, the receipt names "
                f"{receipt.corpus_fingerprint[:12]}. The answer was not re-compared: "
                "against different source text it would not mean anything."
            ),
            receipt_id=receipt.receipt_id,
        )
    current_config = config_digest(cfg)
    if current_config != receipt.config_digest:
        return Verification(
            verdict=Verdict.CONFIGURATION_CHANGED,
            detail=(
                f"the effective configuration is now {current_config[:12]}, the "
                f"receipt names {receipt.config_digest[:12]}. The answer was not "
                "re-compared: a different configuration is a different system."
            ),
            receipt_id=receipt.receipt_id,
        )

    answer = recompute()
    current = receipt_for(
        answer,
        question=receipt.question,
        corpus_fingerprint=corpus_fingerprint,
        cfg=cfg,
        # The receipt's own jurisdiction, not this deployment's default. The
        # caller is required to have recomputed under it (see `recompute`);
        # taking it from the config here would let the two disagree silently,
        # and the disagreement is exactly what the field exists to catch.
        jurisdiction=receipt.jurisdiction,
    )
    if current.digest == receipt.digest:
        return Verification(
            verdict=Verdict.MATCH,
            detail=(
                "this deployment, on this corpus and this configuration, gives "
                "exactly the answer the receipt records."
            ),
            receipt_id=receipt.receipt_id,
        )

    differences = []
    if current.kind != receipt.kind:
        differences.append(f"kind {receipt.kind} -> {current.kind}")
    if current.lang != receipt.lang:
        differences.append(f"language {receipt.lang} -> {current.lang}")
    if current.answer_sha256 != receipt.answer_sha256:
        differences.append("answer text")
    if current.citations != receipt.citations:
        differences.append("cited passages")
    if current.cairn_version != receipt.cairn_version:
        differences.append(f"cairn {receipt.cairn_version} -> {current.cairn_version}")
    return Verification(
        verdict=Verdict.ANSWER_DIFFERS,
        detail="same corpus and configuration, different output: "
        + ", ".join(differences or ["no field differs, but the digests do"]),
        receipt_id=receipt.receipt_id,
    )


def render(verification: Verification) -> str:
    """The plain-text report `cairn verify-receipt` prints."""
    lines = [verification.verdict.value.upper()]
    if verification.receipt_id:
        lines[0] += f"  (receipt {verification.receipt_id})"
    lines.append(f"  {verification.detail}")
    return "\n".join(lines)
