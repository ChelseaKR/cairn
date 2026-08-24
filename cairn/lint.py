"""Corpus linting: read-only checks an author runs before publishing.

`cairn lint` walks the corpus the way `cairn index` would, but it never
writes an index and it does not stop at the first problem. Two failure modes
this project has already measured by hand become findings here instead of a
live refusal or a silent reachability gap discovered too late:

- a passage that tokenizes to no scoring terms at all — title included, at
  the same weight `cairn index` would use — so no question, however phrased,
  can ever retrieve it;
- a language with too few passages for the document-frequency floor to
  suppress anything, which `Index.languages[...].dilution_exempt` already
  computes (see DESIGN.md, "The document-frequency floor has one exemption,
  and it is narrow").

Nothing here changes an index, a score, or an answer. A clean lint is not a
guarantee of good retrieval — it cannot see the `ck-015` kind of gap, where a
passage has plenty of scoring terms and simply is not, lexically, an answer
to a question a plain reader would ask. It only catches what is checkable
without a question in hand: structure, and reachability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cairn.config import Config
from cairn.corpus import CorpusError, Document, corpus_paths, load_document
from cairn.index import TITLE_WEIGHT, build_index
from cairn.retrieve import single_term_scores
from cairn.text import tokenize

# The built-in default, not a live deployment's own — `lint_corpus` takes an
# explicit `threshold` for that; this is only what a caller checking a
# corpus with no config in hand gets.
DEFAULT_THRESHOLD = Config().threshold

Severity = str  # "error" | "warning"


@dataclass(frozen=True)
class LintIssue:
    severity: Severity
    path: str
    message: str


@dataclass(frozen=True)
class LintReport:
    corpus_dir: str
    doc_count: int
    issues: tuple[LintIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        """No errors. Warnings do not fail a lint — they are worth reading,
        not worth blocking on; only a structural problem `cairn index` would
        itself refuse (or silently mis-load) is an error here."""
        return self.error_count == 0


def _load_documents(corpus_dir: str | Path) -> tuple[list[Document], list[LintIssue]]:
    """Every document that parses, and an issue for every one that does not.

    Mirrors `load_corpus`'s own rules — front matter, doc id grammar,
    chunking, duplicate ids — rather than reimplementing them, so a lint that
    calls a corpus clean cannot diverge from what `cairn index` would accept.
    The one deliberate difference: `load_corpus` stops at the first bad file,
    which is the right behavior for something about to answer questions and
    the wrong one for an author fixing a corpus one mistake at a time.
    """
    issues: list[LintIssue] = []
    docs: list[Document] = []
    seen: dict[str, str] = {}
    # Markdown only: corpus_paths also names structured tables (cairn.tabular)
    # since 2026-08-22, so it can be hashed into the corpus fingerprint. This
    # mirrors load_corpus's own filter — tables have no front matter to lint
    # against, and a malformed one is refused outright by cairn.tabular at
    # index time rather than reported here as an advisory issue.
    for path in corpus_paths(corpus_dir):
        if path.suffix.lower() != ".md":
            continue
        try:
            doc = load_document(path)
        except CorpusError as exc:
            issues.append(LintIssue("error", str(path), str(exc)))
            continue
        if doc.doc_id in seen:
            issues.append(
                LintIssue(
                    "error",
                    doc.path,
                    f"duplicate doc id {doc.doc_id!r} (already used by {seen[doc.doc_id]})",
                )
            )
            continue
        seen[doc.doc_id] = doc.path
        docs.append(doc)
    return docs, issues


def _staleness_issues(
    docs: list[Document], *, max_age_days: int, as_of: date
) -> list[LintIssue]:
    """`reviewed_at` is optional and inert to everything that answers a
    question (see `cairn.corpus`'s module docstring) — this is the one thing
    that reads it, and only when an operator explicitly asks by passing
    `--max-age-days`. Silence by default: a corpus that has never adopted the
    convention should not get a warning per document just for existing.
    """
    issues: list[LintIssue] = []
    for doc in docs:
        if doc.reviewed_at is None:
            issues.append(
                LintIssue(
                    "warning",
                    doc.path,
                    "no 'reviewed_at' front-matter key: staleness cannot be tracked for "
                    "this document. Add 'reviewed_at: YYYY-MM-DD' the next time it is "
                    "checked against its real source.",
                )
            )
            continue
        try:
            reviewed = date.fromisoformat(doc.reviewed_at)
        except ValueError:
            issues.append(
                LintIssue(
                    "warning",
                    doc.path,
                    f"'reviewed_at: {doc.reviewed_at}' is not a valid ISO date "
                    f"(YYYY-MM-DD); staleness cannot be checked for this document.",
                )
            )
            continue
        age = (as_of - reviewed).days
        if age > max_age_days:
            issues.append(
                LintIssue(
                    "warning",
                    doc.path,
                    f"last reviewed on {reviewed.isoformat()}, {age} day(s) ago — over "
                    f"the {max_age_days}-day staleness window. Confirm it still matches "
                    f"its real source and update 'reviewed_at'.",
                )
            )
    return issues


def _empty_passage_issues(
    docs: list[Document],
) -> tuple[set[str], list[LintIssue]]:
    empty_passages: set[str] = set()
    issues: list[LintIssue] = []
    for doc in docs:
        for passage in doc.passages:
            # The exact text `cairn index` scores this passage on: title,
            # repeated at TITLE_WEIGHT, ahead of the body. Anything else would
            # be a second, drifting idea of what "has scoring terms" means.
            scored = tokenize(f"{passage.title}\n" * TITLE_WEIGHT + passage.text)
            if not scored:
                empty_passages.add(passage.passage_id)
                issues.append(
                    LintIssue(
                        "warning",
                        doc.path,
                        f"passage {passage.passage_id!r} has no scoring terms after "
                        f"tokenization (title included): no question can retrieve it",
                    )
                )
    return empty_passages, issues


def _reachability_issues(
    corpus_dir: str | Path,
    docs: list[Document],
    empty_passages: set[str],
    threshold: float,
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    index = build_index(corpus_dir)
    for lang, stats in sorted(index.languages.items()):
        if stats.dilution_exempt:
            issues.append(
                LintIssue(
                    "warning",
                    f"[{lang}]",
                    f"{stats.passage_count} passage(s) in {lang!r}: too few for the "
                    f"document-frequency floor to suppress anything, so every term "
                    f"is exempted from suppression rather than scored down (see "
                    f"DESIGN.md, 'The document-frequency floor has one exemption'). "
                    f"Add more {lang!r} content to let the floor engage normally.",
                )
            )
    doc_paths = {doc.doc_id: doc.path for doc in docs}
    for indexed in index.passages:
        if indexed.passage_id in empty_passages:
            continue  # already reported, and every single-term score is 0.0 anyway
        stats = index.stats_for(indexed.lang)
        scores = single_term_scores(indexed, stats)
        best = max(scores.values(), default=0.0)
        if best < threshold:
            issues.append(
                LintIssue(
                    "warning",
                    doc_paths[indexed.doc_id],
                    f"no single term in {indexed.passage_id!r} would clear "
                    f"retrieval.threshold ({threshold:.3f}) alone (best {best:.3f}). "
                    f"Not proof it is unreachable — a combination of otherwise-common "
                    f"terms can still retrieve it together (see DESIGN.md, `ck-022`) — "
                    f"only that no one-word question naming a term it holds will.",
                )
            )
    return issues


def lint_corpus(
    corpus_dir: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_age_days: int | None = None,
    as_of: date | None = None,
) -> LintReport:
    """Check every document under `corpus_dir`.

    Raises `CorpusError` for exactly what `corpus_paths` already refuses —
    no such directory, or no `*.md` documents in it — because a lint with no
    corpus to read is not a report, it is nothing. Everything checkable per
    document becomes a finding instead of a stop.

    `threshold` is `retrieval.threshold` from whatever config the caller is
    actually running — `cairn lint` passes `cfg.threshold` — because the
    reachability check below means nothing against the wrong number.

    `max_age_days` opts into the staleness check (see `_staleness_issues`);
    `None` (the default) runs none of it, so a corpus with no `reviewed_at`
    anywhere stays exactly as quiet as it was before this existed. `as_of`
    exists for tests to pin a date; the CLI passes today's.
    """
    docs, issues = _load_documents(corpus_dir)
    if max_age_days is not None:
        issues += _staleness_issues(
            docs, max_age_days=max_age_days, as_of=as_of or date.today()
        )
    empty_passages, empty_issues = _empty_passage_issues(docs)
    issues += empty_issues
    # Reachability needs a real index, and `build_index` re-reads the corpus
    # from scratch rather than re-parsing `docs` — the one call that can
    # afford that, since a lint runs once per author edit, not once per
    # question. Skipped when a structural error already stands: an index
    # built around a corpus lint has already flagged as broken would just
    # repeat what `load_corpus` itself would refuse.
    if docs and not any(i.severity == "error" for i in issues):
        issues += _reachability_issues(corpus_dir, docs, empty_passages, threshold)
    ordered = tuple(sorted(issues, key=lambda i: (i.path, i.message)))
    return LintReport(corpus_dir=str(corpus_dir), doc_count=len(docs), issues=ordered)


def render(report: LintReport) -> str:
    lines = [f"Linted {report.doc_count} document(s) in {report.corpus_dir}"]
    if not report.issues:
        lines.append("No issues found.")
        return "\n".join(lines)
    for issue in report.issues:
        lines.append(f"  {issue.severity.upper():7} {issue.path}: {issue.message}")
    lines.append(f"{report.error_count} error(s), {report.warning_count} warning(s)")
    return "\n".join(lines)
