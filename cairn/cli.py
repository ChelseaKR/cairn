"""Command-line interface.

Subcommands:

    cairn index            build the local index; report what was indexed
    cairn lint             check the corpus for problems, without indexing
    cairn ask "QUESTION"   answer from the index, or refuse with no sources
    cairn ask --explain    the same, plus the operator retrieval trace
    cairn serve            the accessible chat interface, on localhost
    cairn record           record an evidence bundle for the pinned auditor

Exit codes: 0 for success — including refusals, which are a first-class
outcome, not an error (DESIGN.md); 1 for real errors (bad config, missing
index, malformed corpus, unsupported language).

Right-to-left answers are printed with bidi isolates around the Latin runs
(passage ids, contact numbers). A terminal is a bidi renderer like any other,
and an unisolated ``grocery-allowance-ar#2`` inside an Arabic line has its
punctuation reordered on screen.
"""

from __future__ import annotations

import argparse
import json
import sys

from cairn import __version__
from cairn.config import Config, ConfigError, load_config
from cairn.corpus import CorpusError
from cairn.engine import AskResult, EngineError, ask
from cairn.explain import diagnose, render, trace_payload
from cairn.index import IndexError_, build_and_write, read_index
from cairn.language import isolate
from cairn.lint import lint_corpus
from cairn.lint import render as render_lint_report
from cairn.messages import text as message
from cairn.record import DEFAULT_BUNDLE, DEFAULT_QUESTIONS, RecordError, record
from cairn.server import serve


def _cmd_index(args: argparse.Namespace, cfg: Config) -> int:
    report = build_and_write(cfg.corpus_path, cfg.index_path)
    synthetic_note = ""
    if report.synthetic_doc_count:
        synthetic_note = f" ({report.synthetic_doc_count} marked synthetic)"
    print(
        f"Indexed {report.passage_count} passages from {report.doc_count} "
        f"documents{synthetic_note} in {len(report.languages)} languages "
        f"[{', '.join(report.languages)}] -> {report.index_path}"
    )
    # The receipt. This index answers for exactly the corpus that hashes to
    # this, and every later command checks it before quoting anything; a
    # changed line here after an edit is the whole point of the fingerprint
    # being visible rather than only internal.
    print(f"Corpus fingerprint: {report.corpus_fingerprint[:12]} ({cfg.corpus_path})")
    return 0


def _cmd_lint(args: argparse.Namespace, cfg: Config) -> int:
    report = lint_corpus(cfg.corpus_path)
    print(render_lint_report(report))
    # Warnings do not fail the command — they are advisory, not a defect
    # `cairn index` would itself refuse — but a structural error does, the
    # same way any other subcommand reports a real problem: exit 1.
    return 0 if report.ok else 1


def _render_answer(result: AskResult) -> str:
    answer = result.answer
    rtl = answer.direction == "rtl"
    lines = []
    if answer.notice:
        lines += [answer.notice, ""]
    lines.append(answer.text)
    if answer.kind == "refusal":
        return "\n".join(lines)
    lines += ["", message("sources_heading", answer.lang)]
    for n, source in enumerate(answer.sources, start=1):
        reference = f"{source.title} ({source.source_id})"
        lines.append(f"  [{n}] {isolate(reference) if rtl else reference}")
    return "\n".join(lines)


def _cmd_ask(args: argparse.Namespace, cfg: Config) -> int:
    index = read_index(cfg.index_path, cfg.corpus_path)
    result = ask(args.question, index, cfg, lang=args.lang)
    answer = result.answer
    diagnosis = diagnose(answer, max_passages=cfg.max_passages) if args.explain else None

    if args.json:
        payload = answer.to_payload()
        if diagnosis is not None:
            payload["explain"] = {
                **trace_payload(answer.trace),
                "diagnosis": diagnosis.to_payload(),
                "language": result.detection.to_payload(),
                "attempts": [a.to_payload() for a in result.attempts],
                "cross_language": result.cross_language,
            }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    if diagnosis is not None:
        summary = (
            f"{index.passage_count} passages from {index.doc_count} documents "
            f"({cfg.index_path})"
        )
        print(render(result, diagnosis, index_summary=summary))
        print()
    print(_render_answer(result))
    return 0


def _cmd_serve(args: argparse.Namespace, cfg: Config) -> int:
    index = read_index(cfg.index_path, cfg.corpus_path)
    httpd = serve(cfg, index, host=args.host, port=args.port, quiet=args.quiet)
    host, port = httpd.server_address[0], httpd.server_address[1]
    print(f"cairn: serving the chat interface on http://{host}:{port}/  (ctrl-c to stop)")
    print(
        f"cairn: {index.passage_count} passages, {index.doc_count} documents, "
        f"languages {', '.join(index.language_codes)}"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()  # keep the shell prompt off the ^C line
    finally:
        httpd.server_close()
    return 0


def _cmd_record(args: argparse.Namespace, cfg: Config) -> int:
    index = read_index(cfg.index_path, cfg.corpus_path)
    report = record(index, cfg, questions_path=args.questions, out_dir=args.out)
    print(
        f"Recorded {report.item_count} items "
        f"({report.answer_count} answers, {report.refusal_count} refusals) "
        f"in {len(report.languages)} languages [{', '.join(report.languages)}] "
        f"-> {report.path}"
    )
    print(f"Bundle sha256: {report.bundle_sha256}")
    return 0


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

    p_lint = sub.add_parser(
        "lint", help="check the corpus for problems, without building an index"
    )
    p_lint.set_defaults(func=_cmd_lint)

    p_ask = sub.add_parser("ask", help="ask a question against the index")
    p_ask.add_argument("question", help="the question, quoted")
    p_ask.add_argument("--json", action="store_true", help="machine-readable output")
    p_ask.add_argument(
        "--explain",
        action="store_true",
        help=(
            "operator explain mode: every scored candidate, its accept/reject verdict "
            "at the threshold, and a per-stage diagnosis of the outcome"
        ),
    )
    p_ask.add_argument(
        "--lang",
        metavar="CODE",
        default=None,
        help=(
            "answer in this language and prefer its sources (en, es, ar). "
            "Omit to detect the language from the question."
        ),
    )
    p_ask.set_defaults(func=_cmd_ask)

    p_serve = sub.add_parser("serve", help="serve the accessible chat interface")
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1, i.e. this machine only)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="port to bind (default: 8765; 0 picks a free one)",
    )
    p_serve.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "do not write a line per request. Nothing about a question is ever "
            "logged either way; this silences the request lines so an automated "
            "run against the server reads as its own output."
        ),
    )
    p_serve.set_defaults(func=_cmd_serve)

    p_record = sub.add_parser(
        "record",
        help="record an evidence bundle from the real engine, for the pinned auditor",
    )
    p_record.add_argument(
        "--questions",
        default=DEFAULT_QUESTIONS,
        help=f"question set (default: {DEFAULT_QUESTIONS})",
    )
    p_record.add_argument(
        "--out", default=DEFAULT_BUNDLE, help=f"bundle directory (default: {DEFAULT_BUNDLE})"
    )
    p_record.set_defaults(func=_cmd_record)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        return args.func(args, cfg)
    except (ConfigError, CorpusError, IndexError_, EngineError, RecordError) as exc:
        print(f"cairn: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
