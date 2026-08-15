"""Command-line interface.

Subcommands:

    cairn index            build the local index; report what was indexed
    cairn ask "QUESTION"   answer from the index, or refuse with no sources
    cairn serve            (milestone M4) accessible chat UI

Exit codes: 0 for success — including refusals, which are a first-class
outcome, not an error (DESIGN.md); 1 for real errors (bad config, missing
index, malformed corpus); 2 for not-yet-implemented milestone stubs.
"""

from __future__ import annotations

import argparse
import json
import sys

from cairn import __version__
from cairn.answer import Answer, compose
from cairn.config import Config, ConfigError, load_config
from cairn.corpus import CorpusError
from cairn.index import IndexError_, build_and_write, read_index
from cairn.retrieve import retrieve

STUB_EXIT_CODE = 2


def _cmd_index(args: argparse.Namespace, cfg: Config) -> int:
    report = build_and_write(cfg.corpus_path, cfg.index_path)
    synthetic_note = (
        f" ({report.synthetic_doc_count} marked synthetic)" if report.synthetic_doc_count else ""
    )
    print(
        f"Indexed {report.passage_count} passages from {report.doc_count} "
        f"documents{synthetic_note} -> {report.index_path}"
    )
    return 0


def _render_answer(answer: Answer) -> str:
    if answer.kind == "refusal":
        return answer.text
    lines = [answer.text, "", "Sources:"]
    for n, source in enumerate(answer.sources, start=1):
        lines.append(f"  [{n}] {source.title} ({source.source_id})")
    return "\n".join(lines)


def _cmd_ask(args: argparse.Namespace, cfg: Config) -> int:
    if args.explain:
        print(
            "cairn: --explain (operator explain mode) arrives in milestone M2; "
            "see the roadmap in DESIGN.md.",
            file=sys.stderr,
        )
        return STUB_EXIT_CODE
    if args.lang:
        print(
            "cairn: --lang (language selection) arrives in milestone M3; "
            "see the roadmap in DESIGN.md.",
            file=sys.stderr,
        )
        return STUB_EXIT_CODE
    index = read_index(cfg.index_path)
    trace = retrieve(
        args.question, index, threshold=cfg.threshold, candidates=cfg.candidates
    )
    answer = compose(trace, max_passages=cfg.max_passages, contact=cfg.contact)
    if args.json:
        print(json.dumps(answer.to_payload(), ensure_ascii=False, sort_keys=True))
    else:
        print(_render_answer(answer))
    return 0


def _cmd_serve(args: argparse.Namespace, cfg: Config) -> int:
    print(
        "cairn: serve (accessible chat interface) arrives in milestone M4; "
        "see the roadmap in DESIGN.md. Until then, `cairn ask` is the demo path.",
        file=sys.stderr,
    )
    return STUB_EXIT_CODE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cairn",
        description=(
            "Retrieval-grounded question answering for public agencies: answers only "
            "from an operator-supplied corpus, cites its sources, refuses when it has none."
        ),
    )
    parser.add_argument("--version", action="version", version=f"cairn {__version__}")
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="path to cairn.toml (default: ./cairn.toml if present, else built-in defaults)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build the local index from the corpus")
    p_index.set_defaults(func=_cmd_index)

    p_ask = sub.add_parser("ask", help="ask a question against the index")
    p_ask.add_argument("question", help="the question, quoted")
    p_ask.add_argument("--json", action="store_true", help="machine-readable output")
    p_ask.add_argument(
        "--explain",
        action="store_true",
        help="operator explain mode: candidate scores and threshold verdicts (milestone M2)",
    )
    p_ask.add_argument(
        "--lang",
        metavar="CODE",
        default=None,
        help="response language selection (milestone M3)",
    )
    p_ask.set_defaults(func=_cmd_ask)

    p_serve = sub.add_parser("serve", help="serve the accessible chat UI (milestone M4)")
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        return args.func(args, cfg)
    except (ConfigError, CorpusError, IndexError_) as exc:
        print(f"cairn: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
