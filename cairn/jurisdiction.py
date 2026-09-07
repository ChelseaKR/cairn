"""Jurisdiction codes: the layer a document applies to, and how layers nest.

A corpus assembled for a county deployment is not one corpus. It is federal
pages, plus state pages, plus that county's own — the shape
``assemble_corpus.py`` builds and ``layers.json`` records. Until now the
engine did not know that. A Sonoma resident asking about office hours could
be answered from a Siskiyou page and nothing anywhere would say so; the
pilot's sweep labelled it ``jurisdiction-mismatch`` afterwards, from a file
the engine never reads.

A jurisdiction code names the area a document's text applies to::

    us              federal
    us-ca           California
    us-ca-sonoma    Sonoma County

Hyphen-separated lowercase segments. The first two levels are deliberately
the ISO 3166-1 / 3166-2 spelling (``us``, ``us-ca``) because that is what a
reader already knows how to interpret; deeper segments are the operator's
own naming and this module makes no claim about them.

**Every hyphen is a layer boundary**, which is the one thing to know before
naming a county. ``us-ca-los-angeles`` has four segments, so widening from it
steps through ``us-ca-los`` — a code no document carries. That rung matches
nothing, contributes nothing, and is skipped in a single pass; it is
harmless. An operator who would rather not see it in an explain trace should
write the county as one segment (``us-ca-losangeles``). Splitting on hyphens
rather than string-prefixing is not a detail: ``us-ca`` is a *string* prefix
of ``us-california`` while covering none of it, and a containment test built
on string prefixes would quietly claim a Californian page for an unrelated
jurisdiction that happened to spell its name that way.

Nothing here reads a corpus, a config or an index. It is the vocabulary the
rest of the system agrees on, kept in one place so a code cannot mean two
things — the same reason writing direction lives in :mod:`cairn.language`.
"""

from __future__ import annotations

import re

# Lowercase alphanumeric segments joined by single hyphens. Deliberately
# narrow: a jurisdiction code is written into front matter, a config file, a
# query string, a CLI flag and an HTML form value, and a grammar that is legal
# in all five without quoting or escaping is one that never has to be escaped
# in any of them.
CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SEPARATOR = "-"


class JurisdictionError(ValueError):
    """A jurisdiction code is not a jurisdiction code."""


def validate(code: str, *, where: str) -> str:
    """Return ``code`` unchanged, or raise saying where it came from.

    ``where`` is the caller's own description of the source — a file path, a
    config key, a flag name — because this is raised at four different edges
    and "invalid jurisdiction" with no location is a message an operator
    cannot act on.
    """
    if not CODE.match(code):
        raise JurisdictionError(
            f"{where}: {code!r} is not a jurisdiction code. Expected "
            f"lowercase alphanumeric segments joined by single hyphens, "
            f"outermost first — 'us', 'us-ca', 'us-ca-sonoma'."
        )
    return code


def segments(code: str) -> tuple[str, ...]:
    """The layers a code names, outermost first."""
    return tuple(code.split(SEPARATOR))


def ladder(code: str | None) -> tuple[str | None, ...]:
    """The search order for ``code``: itself, then each wider layer.

    ``('us-ca-sonoma', 'us-ca', 'us')``. ``None`` — no jurisdiction asked for
    — gives ``(None,)``, one unrestricted pass, which is exactly what the
    engine did before jurisdictions existed and is why a corpus that carries
    none is untouched by any of this.

    Most specific first, because that is the preference the whole feature
    exists to state: the county's own page is the applicable one, and a state
    page is the honest fallback rather than an equal candidate.
    """
    if code is None:
        return (None,)
    parts = segments(code)
    return tuple(SEPARATOR.join(parts[:n]) for n in range(len(parts), 0, -1))


def covers(wider: str, narrower: str) -> bool:
    """Does ``wider`` contain ``narrower``? Equality counts.

    Compared segment by segment, never as a string prefix — see the module
    docstring for why ``us-ca`` must not be found to cover ``us-california``.
    """
    outer, inner = segments(wider), segments(narrower)
    return len(outer) <= len(inner) and inner[: len(outer)] == outer
