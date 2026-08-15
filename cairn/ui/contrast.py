"""The interface's colour pairs, read from the stylesheet itself.

One list, two consumers: the test suite computes WCAG ratios from it, and the
interface snapshot in an evidence bundle declares it so an auditor can compute
the same ratios independently. Neither is allowed to have its own idea of what
colours the page uses, and neither takes a claim of conformance on trust.
"""

from __future__ import annotations

import re
from pathlib import Path

STYLESHEET = Path(__file__).resolve().parent / "static" / "app.css"

DARK_BLOCK = "@media (prefers-color-scheme: dark)"
_TOKEN = re.compile(r"--([a-z-]+):\s*(#[0-9a-f]{6})")

# (name, foreground token, background token, WCAG size class). "large" is the
# 3:1 class, which is also the threshold for non-text user interface
# components: borders, focus rings, and the like.
PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("body text", "text", "bg", "normal"),
    ("text on a raised surface", "text", "surface", "normal"),
    ("text on the cross-language notice", "text", "notice-bg", "normal"),
    ("hints and secondary labels", "muted", "bg", "normal"),
    ("secondary text on a raised surface", "muted", "surface", "normal"),
    ("send button", "accent-text", "accent", "normal"),
    ("error message", "alert-text", "alert-bg", "normal"),
    ("control borders", "border", "bg", "large"),
    ("control borders on a raised surface", "border", "surface", "large"),
    ("focus ring", "focus", "bg", "large"),
    ("focus ring on a raised surface", "focus", "surface", "large"),
    ("disclosure accent bar", "accent", "bg", "large"),
    ("error border", "alert-border", "alert-bg", "large"),
)


def palette(scheme: str = "light", css: str | None = None) -> dict[str, str]:
    """Resolved custom properties for one colour scheme."""
    css = css if css is not None else STYLESHEET.read_text(encoding="utf-8")
    tokens = dict(_TOKEN.findall(css.split("@media")[0]))
    if scheme == "dark":
        dark = css.split(DARK_BLOCK, 1)[1].split("}\n}", 1)[0]
        tokens.update(_TOKEN.findall(dark))
    return tokens


def declarations(scheme: str = "light", css: str | None = None) -> list[dict[str, str]]:
    """The colour pairs, resolved, in the shape an auditor can check."""
    tokens = palette(scheme, css)
    return [
        {
            "name": f"{name} ({scheme})",
            "foreground": tokens[foreground],
            "background": tokens[background],
            "size": size,
        }
        for name, foreground, background, size in PAIRS
    ]
