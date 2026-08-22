"""The effective configuration, reported against its built-in defaults.

Read-only: this loads nothing itself and introduces no second config path —
it takes the `Config` `cairn.cli` already built the ordinary way (defaults
plus `cairn.toml` overrides) and echoes each field back next to the built-in
default, so an operator about to change a value sees what they are diverging
from at the moment it matters, rather than having to read DESIGN.md's
"Configuration" table separately.

The rationale table below is hand-maintained prose, deliberately kept to one
line pointing at DESIGN.md rather than restating the reasoning there — a
restatement is a second copy that can drift when the original changes; a
pointer cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from cairn.config import Config

# One line per load-bearing key DESIGN.md gives a measured rationale for. Not
# every field needs one — `corpus_path` and `index_path` are locations, not
# tuned values — so a missing entry here is not itself a gap.
_RATIONALE: dict[str, str] = {
    "threshold": (
        "DESIGN.md, 'Configuration' note — measured against the demo corpus; "
        "re-check against probe questions when the corpus changes"
    ),
    "max_passages": (
        "DESIGN.md, 'Configuration' — raised from 2 to 1 after the first audit "
        "found each language composing a different second passage for the same fact"
    ),
    "candidates": (
        "DESIGN.md, 'Configuration' — widens what --explain reports; retrieval "
        "quality does not depend on it"
    ),
    "margin_warn": (
        "cairn/config.py — diagnostic only; smaller than the measured "
        "calibration gap so it does not fire on ordinary in-corpus answers"
    ),
}


@dataclass(frozen=True)
class ConfigDiffRow:
    key: str
    effective: object
    default: object
    overridden: bool
    rationale: str | None


def diff_from_defaults(cfg: Config) -> tuple[ConfigDiffRow, ...]:
    """Every `Config` field, next to the value `Config()` gives it."""
    defaults = Config()
    rows = []
    for f in fields(Config):
        effective = getattr(cfg, f.name)
        default = getattr(defaults, f.name)
        rows.append(
            ConfigDiffRow(
                key=f.name,
                effective=effective,
                default=default,
                overridden=effective != default,
                rationale=_RATIONALE.get(f.name),
            )
        )
    return tuple(rows)


def render(rows: tuple[ConfigDiffRow, ...]) -> str:
    lines: list[str] = []
    for row in rows:
        marker = "*" if row.overridden else " "
        lines.append(f"{marker} {row.key} = {row.effective!r}")
        if row.overridden:
            lines.append(f"    default: {row.default!r}")
            if row.rationale:
                lines.append(f"    see: {row.rationale}")
    if not any(row.overridden for row in rows):
        lines.append("(no overrides — every value is the built-in default)")
    return "\n".join(lines)
