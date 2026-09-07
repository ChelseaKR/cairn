"""`cairn init`: scaffold a deployment with both audit interlocks in it.

An agency adopting Cairn installs the package and gets the engine. It does not
get the part of this project that is not a demo: two independent harnesses,
each pinned to an exact commit, grading a recorded evidence bundle produced by
the engine itself, with a committed baseline that a score cannot decay past.
That machinery lives at the root of Cairn's own repository, shaped for Cairn's
own corpus, and a reader has to reconstruct it from DESIGN.md.

Shipping the engine without the interlock ships the confident-wrong-answer risk
without the check. This verb makes "audited by a pinned external harness" the
default shape of a deployment.

**Everything written here is unfinished on purpose.** The refusal contact is
blank, the question set is a draft `cairn record` refuses as it stands, and
the audit baseline is a placeholder that fails. None of those are gaps: each
is a decision only a person who has read the corpus can make, and a scaffold
that filled them in with something plausible would be handing an agency a
green gate it never earned. The README this writes names every one of them.

Offline, deterministic, and it refuses to overwrite.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from cairn import __version__
from cairn.corpus import CorpusError, load_corpus

TEMPLATE_PACKAGE = "cairn.templates"

# The suites the pinned harness declares, in the order Cairn's own
# `plumbline/target.toml` declares them.
#
# Held here as a list rather than read out of that file, because at run time
# there is no repository — a deployment scaffolded from a wheel has the
# package and nothing else. `tests/test_scaffold.py` holds this equal to
# Cairn's own target file, so the two cannot drift; a suite the harness adds
# and this list does not name is a suite nobody is being graded on, and after
# a pin bump that is a question rather than a detail.
SUITES = (
    "smoke",
    "accuracy",
    "refusal",
    "cross_language",
    "multilingual",
    "groundedness",
    "citation_validity",
    "citation_accuracy",
    "adversarial",
    "fairness",
    "representational_harms",
    "privacy",
    "accessibility",
    "passage_attribution",
    "conversational_integrity",
)

# The pin files ship verbatim, rather than being rebuilt here from a commit
# hash held as a constant.
#
# The first draft did hold the hashes as constants, and `tests/
# test_gauntlet_interlock.py` was right to fail it: "one place names the
# commit; a second unreviewed copy is how a pin stops meaning anything". A
# constant in this module would have been exactly that copy, and it would
# have gone stale silently at the first pin bump.
#
# Shipping the files themselves moves the problem to one a test can close
# completely: `tests/test_scaffold.py` holds each template byte-equal to the
# pin at this repository's root, and the interlock test now names the one
# place the copy is allowed to be. A scaffolded deployment therefore gets the
# pins this release was actually audited with, by construction.

# Every placeholder any template may carry. Checked by name rather than by
# scanning for `{{...}}`, because `audit.yml` is full of GitHub Actions
# expressions (`${{ github.ref }}`) that are not placeholders and must survive
# untouched.
PLACEHOLDERS = ("{{NAME}}", "{{CORPUS_PATH}}", "{{VERSION}}", "{{SUITES}}")

# Files written with the executable bit, because they are run as `./name`.
EXECUTABLE = ("plumbline-gate.sh", "gauntlet-gate.sh")


class ScaffoldError(ValueError):
    """Nothing has been written when this is raised."""


@dataclass(frozen=True)
class InitReport:
    directory: str
    corpus_path: str
    files: tuple[str, ...]
    drafted_items: int


def template(name: str) -> str:
    """One packaged template, verbatim."""
    return (
        resources.files(TEMPLATE_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    )


def render(body: str, **fields: str) -> str:
    """Substitute the named placeholders, and refuse to leave one behind.

    A template that still says `{{CONTACT}}` after rendering would ship the
    template's own words as if they were the operator's, which is exactly the
    failure `assemble_corpus.render_config` guards against for the pilot's
    config. The check is by placeholder name: a generic sweep for `{{` would
    trip on every `${{ github.ref }}` in the workflow template.
    """
    for key, value in fields.items():
        body = body.replace("{{" + key + "}}", value)
    left = [token for token in PLACEHOLDERS if token in body]
    if left:
        raise ScaffoldError(
            f"template still carries {', '.join(left)} after rendering: a "
            f"placeholder that reaches an operator's file is the template "
            f"speaking in their voice"
        )
    return body


def _suite_block() -> str:
    """Every suite, enabled, with no floor.

    No floor is the point. Each suite then takes the pinned harness's own
    default, chosen by the people who wrote the suite and know what its metric
    means, which is where a new deployment should start. A scaffold that
    guessed floors would be guessing what is good enough for the people this
    deployment serves.
    """
    return "\n\n".join(
        f"[suites.{name}]\nenabled = true" for name in SUITES
    )


def draft_questions(corpus_dir: str | Path) -> tuple[str, int]:
    """A question set drafted from the corpus, and how many items it holds.

    One item per document, carrying the document's own id, language and title
    and nothing else: a blank `prompt`, no `answering_sources`, and a
    `review = "draft"` marker.

    Blank rather than invented. `cairn record` refuses this file exactly as it
    stands, and that refusal is the feature — only a person who has read the
    document can say what question it answers and which passage answers it,
    and a question set full of plausible-looking items nobody checked is a
    check that is not running. The same stance `import_corpus.py` takes with
    `review: unreviewed`, one layer up.
    """
    documents = load_corpus(corpus_dir)
    lines = [
        "# The questions the auditor grades this deployment's answers to.",
        "#",
        "# DRAFTED, NOT WRITTEN. `cairn init` read the corpus and wrote one",
        "# item per document, with an empty prompt and no answering_sources.",
        "# `cairn record` refuses this file as it stands, and will go on",
        "# refusing it until a person fills the items in.",
        "#",
        "# For each item you keep: write a question somebody would really ask,",
        "# the concise correct answer, and the passage id that answers it",
        "# (`<doc-id>#<ordinal>`, which `cairn ask --explain` prints). Then",
        "# delete the `review` marker. Delete the items you are not going to",
        "# write; an item is not evidence because it exists.",
        "#",
        "# behavior is \"answer\" or \"refuse\". A `refuse` item declares no",
        "# answering_sources, because nothing answers a question that should",
        "# not be answered -- and a question set with no refuse items has not",
        "# tested the outcome this engine exists to produce.",
    ]
    for document in documents:
        lines += [
            "",
            "[[item]]",
            f"id = {document.doc_id!r}".replace("'", '"'),
            f"lang = {document.lang!r}".replace("'", '"'),
            'behavior = "answer"',
            'review = "draft"',
            'prompt = ""',
            "expected = \"\"",
            "answering_sources = []",
            f"# from {Path(document.path).name}: {document.title}",
        ]
    return "\n".join(lines) + "\n", len(documents)


def _plan(corpus_dir: Path, corpus_path: str, name: str) -> dict[str, str]:
    """Every file `init` would write, rendered, before anything is written.

    Two paths for the corpus, and they are not interchangeable. `corpus_dir`
    is where the documents are *now*, and is what the question set is drafted
    from; `corpus_path` is what the scaffolded `cairn.toml` should say, which
    is relative to the deployment directory when the corpus sits inside it.
    Passing the second where the first belonged resolved a relative path
    against the process's working directory and drafted from a corpus that was
    not there.
    """
    questions, _ = draft_questions(corpus_dir)
    files = {
        "cairn.toml": render(
            template("cairn.toml"), NAME=name, CORPUS_PATH=corpus_path
        ),
        "questions.toml": questions,
        "README.md": render(
            template("README.md"),
            NAME=name,
            CORPUS_PATH=corpus_path,
            VERSION=__version__,
        ),
        "plumbline/target.toml": render(
            template("target.toml"), NAME=name, SUITES=_suite_block()
        ),
        "plumbline/baseline.json": template("baseline.json"),
        ".github/workflows/audit.yml": render(
            template("audit.yml"), VERSION=__version__
        ),
        "plumbline-gate.sh": template("plumbline-gate.sh"),
        "gauntlet-gate.sh": template("gauntlet-gate.sh"),
        # Verbatim, for the reason set out above the template list.
        "plumbline.pin": template("plumbline.pin"),
        "gauntlet.pin": template("gauntlet.pin"),
    }
    return files


def init(directory: str | Path, corpus: str | Path, *, name: str | None = None) -> InitReport:
    """Scaffold a deployment into ``directory``.

    Refuses before writing anything if a single file it would write is already
    there. Partial output is worse than none: a half-scaffolded directory
    looks finished, and the file it did not overwrite is the one an operator
    had already customised.
    """
    target = Path(directory)
    corpus_dir = Path(corpus)
    if not corpus_dir.is_dir():
        raise ScaffoldError(f"corpus directory not found: {corpus_dir}")
    try:
        load_corpus(corpus_dir)
    except CorpusError as exc:
        raise ScaffoldError(
            f"the corpus cannot be read, so the question set cannot be drafted "
            f"from it: {exc}"
        ) from exc

    corpus_path = _relative_to(corpus_dir, target)
    plan = _plan(corpus_dir, corpus_path, name or target.resolve().name)

    existing = sorted(rel for rel in plan if (target / rel).exists())
    if existing:
        raise ScaffoldError(
            f"{target} already holds {', '.join(existing)}. Nothing was "
            f"written: a half-scaffolded directory looks finished, and the "
            f"file left alone is the one somebody had already customised. "
            f"Scaffold somewhere else, or move these aside first."
        )

    for rel, body in sorted(plan.items()):
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        if rel in EXECUTABLE:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    _, drafted = draft_questions(corpus_dir)
    return InitReport(
        directory=str(target),
        corpus_path=corpus_path,
        files=tuple(sorted(plan)),
        drafted_items=drafted,
    )


def _relative_to(corpus: Path, target: Path) -> str:
    """The corpus path as the scaffolded config should name it.

    Relative when the corpus sits inside the deployment directory, absolute
    otherwise. Not `os.path.relpath` unconditionally: a config that says
    `../../../elsewhere/corpus` breaks the moment the directory is moved, and
    a deployment directory is a thing people move.
    """
    resolved, root = corpus.resolve(), target.resolve()
    if resolved == root or root in resolved.parents:
        return resolved.relative_to(root).as_posix()
    return resolved.as_posix()


def render_report(report: InitReport) -> str:
    lines = [
        f"Scaffolded {report.directory} against corpus {report.corpus_path}:",
        *(f"  {name}" for name in report.files),
        "",
        f"{report.drafted_items} question item(s) drafted, none of them written.",
        "",
        "Three things are deliberately unfinished, and each refuses rather than",
        "guesses:",
        "  [refusal] contact is blank      -> `cairn serve` will not start",
        "  questions.toml is a draft       -> `cairn record` refuses it",
        "  plumbline/baseline.json is fake -> the audit guard fails",
        "",
        f"Read {report.directory}/README.md: it names every step left to a person.",
    ]
    return "\n".join(lines)
