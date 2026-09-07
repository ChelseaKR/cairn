"""A synthetic corpus layered by jurisdiction, for the jurisdiction tests.

Three layers of invented benefit rules for an invented state and county —
federal (``us``), state (``us-ca``) and county (``us-ca-sonoma``) — plus one
sibling county (``us-ca-siskiyou``) whose only job is to be the wrong answer,
and one unlabelled document whose only job is to be a document that never
said where it applies.

Written as text rather than as constructed :class:`~cairn.index.Index`
objects on purpose. Every jurisdiction claim in this system starts life as a
line of front matter an author typed, and a fixture that skipped the parser
would test the half of the feature that cannot be got wrong.

The vocabulary is deliberately disjoint per topic and repeated per document,
so that which passage wins is decided by the topic word and not by an
accident of the document-frequency floor. ``jurisdiction_corpus`` writes the
files; ``layered_index`` builds an index from them once for a whole test run.
"""

from __future__ import annotations

import atexit
import tempfile
from pathlib import Path

from cairn.index import Index, build_index

# (filename, jurisdiction or None, lang, doc id, title, body)
DOCUMENTS: tuple[tuple[str, str | None, str, str, str, str], ...] = (
    (
        "federal-eligibility.en.md",
        "us",
        "en",
        "federal-eligibility-en",
        "Federal eligibility rules for the Harbor nutrition benefit",
        "Federal eligibility for the Harbor nutrition benefit is decided by "
        "household size and by countable income. A household of four with "
        "countable income under the federal limit is eligible.\n\n"
        "Federal rules require every household to report a change in "
        "countable income within ten days of the change.",
    ),
    (
        "state-appeals.en.md",
        "us-ca",
        "en",
        "state-appeals-en",
        "Statewide appeal deadlines for a denied benefit",
        "A statewide appeal of a denied benefit must be filed within ninety "
        "days of the denial notice. The statewide appeal hearing is held by "
        "telephone unless you ask for it in person.\n\n"
        "Statewide policy sets the same ninety day appeal window in every "
        "county, and no county may shorten it.",
    ),
    (
        "state-office-hours.en.md",
        "us-ca",
        "en",
        "state-office-hours-en",
        "Statewide service counter hours",
        "Statewide service counters are open from nine in the morning until "
        "four in the afternoon on weekdays. Statewide counters are closed on "
        "state holidays.",
    ),
    (
        "sonoma-office-hours.en.md",
        "us-ca-sonoma",
        "en",
        "sonoma-office-hours-en",
        "Sonoma service counter hours",
        "The Sonoma service counter is open from eight in the morning until "
        "five in the afternoon on weekdays. The Sonoma counter is closed on "
        "state holidays.",
    ),
    (
        "sonoma-appeals.en.md",
        "us-ca-sonoma",
        "en",
        "sonoma-appeals-en",
        "Sonoma appeal hearings for a denied benefit",
        "A Sonoma appeal of a denied benefit is heard at the Sonoma hearing "
        "room, and a Sonoma appeal may be filed in person or by telephone "
        "within the ninety day appeal window.",
    ),
    (
        "siskiyou-office-hours.en.md",
        "us-ca-siskiyou",
        "en",
        "siskiyou-office-hours-en",
        "Siskiyou service counter hours",
        "The Siskiyou service counter is open from ten in the morning until "
        "three in the afternoon on weekdays. The Siskiyou counter is closed "
        "on state holidays.",
    ),
    (
        "state-appeals.es.md",
        "us-ca",
        "es",
        "state-appeals-es",
        "Plazos estatales de apelación por una prestación denegada",
        "Una apelación estatal de una prestación denegada debe presentarse "
        "dentro de los noventa días del aviso de denegación. La audiencia "
        "estatal de apelación se realiza por teléfono.",
    ),
    (
        "unlabelled-transport.en.md",
        None,
        "en",
        "unlabelled-transport-en",
        "Transport reimbursement for a hearing",
        "Transport reimbursement for attending a hearing is paid at the "
        "published mileage rate. Transport reimbursement is claimed on the "
        "form given to you at the hearing.",
    ),
)


def jurisdiction_corpus(directory: str | Path) -> Path:
    """Write the layered corpus into ``directory`` and return it."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for name, jurisdiction, lang, doc_id, title, body in DOCUMENTS:
        front = [f"id: {doc_id}", f"title: {title}", f"lang: {lang}", "synthetic: true"]
        if jurisdiction is not None:
            front.append(f"jurisdiction: {jurisdiction}")
        (root / name).write_text(
            "---\n" + "\n".join(front) + "\n---\n\n" + body + "\n", encoding="utf-8"
        )
    return root


_CACHE: dict[str, Index] = {}


def layered_index() -> Index:
    """The corpus above, indexed once per process.

    The temporary directory is kept alive for the life of the process and
    removed at exit, because the index carries a corpus fingerprint that
    `read_index` would want to check against a corpus still on disk.
    """
    if "index" not in _CACHE:
        holder = tempfile.TemporaryDirectory()
        atexit.register(holder.cleanup)
        _CACHE["index"] = build_index(jurisdiction_corpus(Path(holder.name) / "corpus"))
    return _CACHE["index"]
