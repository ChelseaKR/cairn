"""Derive a `cairn calibrate` probe file from a `cairn record` question set.

Dev-only, stdlib-only. A probe is a question, a language and an expected
behavior; an evidence item is those three things plus authored ground truth
(`answering_sources`, `expected`, ...). The usa.gov pilot kept
`probes.toml` and `questions.toml` side by side and typed every question
twice, which is two files that will disagree the day one is edited. This
writes the first from the second, so there is one place a question lives.

    python3 probes_from_questions.py corpus/pilot-ca/questions.toml \
        -o corpus/pilot-ca/probes.toml

The output is deterministic for a given input and carries a header saying
where it came from; a test can hold the committed probe file to it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cairn.record import RecordError, load_questions


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(questions: list[dict], *, source: str) -> str:
    lines = [
        f"# Derived from {source} by probes_from_questions.py — do not edit;",
        "# edit the question set and re-run. Every item becomes one probe.",
        "",
    ]
    for question in questions:
        lines.append("[[probe]]")
        lines.append(f"question = {_quote(question['prompt'])}")
        lines.append(f"behavior = {_quote(question['behavior'])}")
        lines.append(f"lang = {_quote(question['lang'])}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write calibrate probes from a question set.")
    parser.add_argument("questions", help="cairn record question set (TOML)")
    parser.add_argument("-o", "--output", required=True, help="probe file to write")
    args = parser.parse_args(argv)
    try:
        questions = load_questions(args.questions)
    except RecordError as exc:
        print(f"probes_from_questions: error: {exc}", file=sys.stderr)
        return 1
    text = render(questions, source=Path(args.questions).as_posix())
    Path(args.output).write_text(text, encoding="utf-8")
    print(f"Wrote {len(questions)} probe(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
