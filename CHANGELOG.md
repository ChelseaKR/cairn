# Changelog

A reference implementation is cited, not installed, and a citation needs a
fixed point. This file is that fixed point's description; the version it names
is `cairn.__version__`, `pyproject.toml`'s `version`, and `CITATION.cff`'s
`version`, held together by a test.

Dates are the date the work landed on `main`. A section is written when the
version is bumped; the annotated tag is cut by the maintainer afterwards,
because tagging is a push and this repository's working rule is that an agent
does not push.

## 0.1.0 — 2026-08-16

First citable version. Everything the functional specification asks for is
implemented and measured, and what is not implemented is written down rather
than left to be discovered — see "What is still open" in
[DESIGN.md](DESIGN.md), where each entry is anchored to a test that fails if
the entry stops being accurate in either direction.

**The behaviour.** Answers are extractive: a grounded answer is a corpus
passage quoted verbatim with an inline citation, so every fact in it, numbers
included, appears character-for-character in a cited source. When no passage
clears the relevance threshold, Cairn refuses, cites nothing, points to a human
and exits 0 — a refusal is an outcome, not an error. Three languages, one of
them right-to-left, with direction derived from the language rather than
configured. When the only source is in another language, Cairn says so in the
language it was asked in and quotes the source untranslated, because
translating a policy amount would produce a number no document contains.

**The machinery for not being believed.** A committed evidence bundle recorded
from the real engine; an external auditor (Plumbline) pinned to an exact
commit, resolved at run time and never a dependency; a committed baseline, so a
score that decays without breaching a floor still fails; an operator explain
mode that attributes a bad answer to retrieval or to composition; and a
guard that fails on any suite silently disabled or any non-default floor with
no reason recorded.

**Runtime dependencies: none.** Standard library only, no model, no network.
The demo runs offline from a clean checkout.

Known limitations at this version, all measured and all written up: a
colloquially-phrased question that shares no words with the corpus is refused
(`ck-015`); one answer comes from the right document's wrong paragraph
(`ck-022`); cross-language retrieval needs the document's own name to survive
the crossing; the audit scores a correct cross-language answer as a failure and
has room for exactly one such item; the branch-protection ruleset is committed
and not applied, so the gate reports rather than blocks; and no manual
screen-reader session has happened.
