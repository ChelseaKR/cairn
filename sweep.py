"""Threshold sweep: the answer-rate / wrong-answer-rate curve for a question set.

Dev-only, stdlib-only, not part of the runtime and not a gate. `cairn
calibrate` answers one question about a probe set: does the configured
threshold classify every probe correctly? The real-corpus pilot
(`docs/pilot-ca.md`) needs a different question: across every threshold an
operator might set, what fraction of answerable questions are answered from
the passage a person said answers them, and what fraction of the answers
given are wrong? The deliverable is the curve, not a point on it, because the
operating point is the agency's choice and the curve is what this project
can honestly hand them.

One engine call per question. Scores do not depend on the threshold — the
threshold is a gate applied *after* scoring (`cairn/retrieve.py`) — so every
candidate's score is read once from the same `RetrievalTrace` that `ask
--explain` prints, and the outcome at every threshold is computed from that.
Nothing here re-implements scoring, ranking or composition: at threshold
`t`, the accepted set is the candidates scoring `>= t` (the engine's own
comparison), and the composed set is the first `max_passages` of them, which
is what `cairn/answer.py` composes.

**The one approximation, stated.** The engine's language-scope fallback
("no same-language passage cleared the threshold, try the whole corpus") is
decided at the *configured* threshold, and the candidates this sweep reads
are the final attempt's. A question that fell back at 0.165 is swept over
its corpus-scope candidates at every threshold, including ones where it
would not have fallen back. Refusals fall back too (nothing cleared in
either scope), so the count printed is "questions whose candidates are the
corpus-scope attempt's", and each is marked `[corpus-scope]` in the
per-question table so a reader can discount them; it is not hidden.

Outcomes, per question and threshold — four cells:

- `correct-answer`: composed passages include one the question set names in
  `answering_sources`;
- `wrong-answer`: something was composed and none of it is an answering
  passage (for a `refuse` question, anything composed at all);
- `correct-refusal`: a `refuse` question with nothing composed;
- `wrong-refusal`: an `answer` question with nothing composed.

Rates: `answer_rate` = correct answers / `answer` questions;
`wrong_answer_rate` = wrong answers / all answers given. Reported overall and
split by every label the question set carries beyond the recorder's own
(`source`, `jurisdiction`, `county`, `location_dependent` in the pilot's
set) — the sweep does not know what those mean and does not need to.

`--at T` prints the per-question table at one threshold with a first-pass
failure label computed from the candidate evidence alone. It is a first
pass — the pilot hand-reviews every failure — and it only claims what the
evidence supports:

- `vocabulary-gap`: no answering passage is a candidate at all (shares no
  scored term with the question);
- `threshold`: refused, and an answering passage is a candidate below `T`
  (lowering the bar would answer it — and admit whatever else sits there);
- `wrong-passage`: answered from a non-answering passage in the same layer
  as the answering one — a ranking loss, whatever the threshold;
- `jurisdiction-mismatch`: as above, but the composed passage is from a
  different layer than the answering one. Read from the engine's own
  decision — every passage now carries its jurisdiction through the index —
  and from `layers.json` only for a corpus assembled before that, so the
  label says what the engine did rather than what a side file implies it
  did;
- `wrong-county`: both layers are county layers;
- `unclassified`: everything else.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cairn.answer import citation_marker
from cairn.config import ConfigError, load_config
from cairn.engine import ask
from cairn.index import IndexError_, read_index
from cairn.jurisdiction import covers
from cairn.record import AUTHORED_FIELDS, RecordError, load_questions

RECORDER_FIELDS = frozenset(AUTHORED_FIELDS) | {"id"}
LAYERS_FILE = "layers.json"

OUTCOMES = ("correct-answer", "wrong-answer", "correct-refusal", "wrong-refusal")


@dataclass(frozen=True)
class Scored:
    """Everything the sweep needs about one question, read once."""

    id: str
    behavior: str
    answering: frozenset[str]  # normalised passage ids
    candidates: tuple[tuple[str, float], ...]  # (normalised passage id, score), ranked
    cross_language: bool
    labels: dict[str, object] = field(default_factory=dict)


def normalise(passage_id: str) -> str:
    return citation_marker(passage_id)


def engine_layers(index) -> dict[str, str]:
    """`{doc_id: jurisdiction}` for every labelled passage in the index.

    The engine's own answer to the question `layers.json` was invented to
    answer, and it is a better one: `layers.json` records which *directory* a
    file was copied from, while this records what the document itself claims
    about where it applies. The two agree for a corpus `assemble_corpus.py`
    built, and only this one exists for a corpus that was not assembled.
    """
    return {p.doc_id: p.jurisdiction for p in index.passages if p.jurisdiction}


def score_questions(questions: list[dict], index, cfg) -> list[Scored]:
    out: list[Scored] = []
    for question in questions:
        result = ask(question["prompt"], index, cfg, lang=question["lang"])
        trace = result.answer.trace
        candidates = tuple(
            (normalise(c.passage.passage_id), c.score) for c in trace.candidates
        )
        labels = {k: v for k, v in question.items() if k not in RECORDER_FIELDS}
        out.append(
            Scored(
                id=question["id"],
                behavior=question["behavior"],
                answering=frozenset(
                    normalise(s) for s in question.get("answering_sources", [])
                ),
                candidates=candidates,
                cross_language=any(a.scope == "corpus" for a in result.attempts),
                labels=labels,
            )
        )
    return out


def composed_at(scored: Scored, threshold: float, max_passages: int) -> tuple[str, ...]:
    accepted = [pid for pid, score in scored.candidates if score >= threshold]
    return tuple(accepted[:max_passages])


def outcome_at(scored: Scored, threshold: float, max_passages: int) -> str:
    composed = composed_at(scored, threshold, max_passages)
    if scored.behavior == "refuse":
        return "wrong-answer" if composed else "correct-refusal"
    if not composed:
        return "wrong-refusal"
    if any(pid in scored.answering for pid in composed):
        return "correct-answer"
    return "wrong-answer"


@dataclass(frozen=True)
class Rates:
    answer_rate: float | None
    wrong_answer_rate: float | None
    counts: dict[str, int]

    @staticmethod
    def of(outcomes: list[str], behaviors: list[str]) -> Rates:
        counts = Counter(outcomes)
        answerable = sum(1 for b in behaviors if b == "answer")
        answered = counts["correct-answer"] + counts["wrong-answer"]
        return Rates(
            answer_rate=(counts["correct-answer"] / answerable) if answerable else None,
            wrong_answer_rate=(counts["wrong-answer"] / answered) if answered else None,
            counts={k: counts.get(k, 0) for k in OUTCOMES},
        )


def sweep(
    scored: list[Scored], thresholds: list[float], max_passages: int
) -> list[tuple[float, Rates]]:
    rows = []
    for t in thresholds:
        outcomes = [outcome_at(s, t, max_passages) for s in scored]
        rows.append((t, Rates.of(outcomes, [s.behavior for s in scored])))
    return rows


def split_keys(scored: list[Scored]) -> list[str]:
    keys: set[str] = set()
    for s in scored:
        keys.update(k for k, v in s.labels.items() if isinstance(v, str | bool | int))
    return sorted(keys)


def rates_by_label(
    scored: list[Scored], key: str, threshold: float, max_passages: int
) -> dict[str, Rates]:
    groups: dict[str, list[Scored]] = {}
    for s in scored:
        if key in s.labels:
            groups.setdefault(str(s.labels[key]), []).append(s)
    return {
        value: Rates.of(
            [outcome_at(s, threshold, max_passages) for s in members],
            [s.behavior for s in members],
        )
        for value, members in sorted(groups.items())
    }


def classify(
    scored: Scored, threshold: float, max_passages: int, layers: dict[str, str]
) -> str:
    """First-pass failure label from candidate evidence alone. See the module
    docstring for what each label does and does not claim."""
    outcome = outcome_at(scored, threshold, max_passages)
    if outcome in ("correct-answer", "correct-refusal"):
        return ""
    if scored.behavior == "refuse":
        return "over-answer"
    in_candidates = {pid: score for pid, score in scored.candidates if pid in scored.answering}
    if not in_candidates:
        return "vocabulary-gap"
    if outcome == "wrong-refusal":
        return "threshold"
    # A wrong answer: something outranked the answering passage. Whether the
    # answering passage itself cleared the threshold is beside the point —
    # lowering the bar would not move it above what beat it.
    composed = composed_at(scored, threshold, max_passages)
    if not layers:
        return "wrong-passage"
    composed_layers = {layers.get(pid.split(".")[0]) for pid in composed}
    answer_layers = {layers.get(pid.split(".")[0]) for pid in in_candidates}
    if composed_layers & answer_layers:
        return "wrong-passage"
    shared = shared_layers(layers)
    if composed_layers - shared and answer_layers - shared:
        return "wrong-county"
    return "jurisdiction-mismatch"


def shared_layers(layers: dict[str, str]) -> set[str]:
    """The layers that are *not* a single county's — the ones every county's
    corpus holds a copy of.

    Two sources, because there are two kinds of label in circulation. A
    corpus assembled by `assemble_corpus.py` before documents carried their
    own jurisdiction is labelled with layer *directory* names, of which
    `federal` and `california` are the pilot's shared pair; those are named
    here because nothing about the string "california" says it is wider than
    the string "sonoma".

    A jurisdiction code does say so, so for those it is derived: a layer is
    shared when some other observed layer sits inside it. `us` and `us-ca`
    each contain `us-ca-sonoma` and are shared; `us-ca-sonoma` contains no
    other observed layer and is a county. Deriving it means a pilot in a
    second state does not have to remember to add a name here — which is
    exactly the kind of hand-kept list this repository keeps replacing with
    the thing it was standing in for.
    """
    values = {value for value in layers.values() if value}
    legacy = {"federal", "california"} & values
    derived = {
        value
        for value in values
        if any(other != value and covers(value, other) for other in values)
    }
    return legacy | derived


def load_layers(corpus_dir: Path) -> dict[str, str]:
    path = corpus_dir / LAYERS_FILE
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        return dict(json.load(handle).get("documents", {}))


def _fmt(rate: float | None) -> str:
    return "   -  " if rate is None else f"{rate:6.3f}"


def render_curve(rows: list[tuple[float, Rates]], configured: float) -> str:
    lines = [
        "threshold  answer_rate  wrong_answer_rate  correct  wrong  c-refuse  w-refuse",
    ]
    for t, r in rows:
        mark = " <- configured" if abs(t - configured) < 1e-9 else ""
        c = r.counts
        lines.append(
            f"  {t:5.3f}     {_fmt(r.answer_rate)}        {_fmt(r.wrong_answer_rate)}       "
            f"{c['correct-answer']:4d}  {c['wrong-answer']:5d}     "
            f"{c['correct-refusal']:4d}    {c['wrong-refusal']:5d}{mark}"
        )
    return "\n".join(lines)


def render_at(
    scored: list[Scored], threshold: float, max_passages: int, layers: dict[str, str]
) -> str:
    lines = [f"At threshold {threshold:.3f}, max_passages {max_passages}:", ""]
    failures = Counter()
    for s in scored:
        outcome = outcome_at(s, threshold, max_passages)
        label = classify(s, threshold, max_passages, layers)
        if label:
            failures[label] += 1
        composed = ", ".join(composed_at(s, threshold, max_passages)) or "-"
        best = f"{s.candidates[0][1]:.3f}" if s.candidates else "  -  "
        flag = " [corpus-scope]" if s.cross_language else ""
        lines.append(
            f"  {s.id:<12} {s.behavior:<7} {outcome:<16} {label:<22} best {best}  "
            f"composed {composed}{flag}"
        )
    lines.append("")
    lines.append("Failure labels (first pass — hand-review every one):")
    for label, count in failures.most_common():
        lines.append(f"  {label:<22} {count}")
    if not failures:
        lines.append("  none")
    for key in split_keys(scored):
        lines.append("")
        lines.append(f"By {key}:")
        for value, r in rates_by_label(scored, key, threshold, max_passages).items():
            lines.append(
                f"  {value:<16} answer_rate {_fmt(r.answer_rate)}  "
                f"wrong_answer_rate {_fmt(r.wrong_answer_rate)}  n={sum(r.counts.values())}"
            )
    return "\n".join(lines)


def thresholds_range(start: float, stop: float, step: float) -> list[float]:
    out = []
    t = start
    while t <= stop + 1e-9:
        out.append(round(t, 4))
        t += step
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Answer-rate / wrong-answer-rate curve over thresholds for a question set."
    )
    parser.add_argument("--config", required=True, help="cairn.toml of an indexed corpus")
    parser.add_argument("--questions", required=True, help="cairn record question set")
    parser.add_argument("--start", type=float, default=0.05)
    parser.add_argument("--stop", type=float, default=0.40)
    parser.add_argument("--step", type=float, default=0.01)
    parser.add_argument(
        "--max-passages",
        type=int,
        default=None,
        help="composition width to model (default: the config's retrieval.max_passages)",
    )
    parser.add_argument("--at", type=float, default=None, help="per-question table at T")
    parser.add_argument("--json", dest="json_out", default=None, help="write the curve here")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        index = read_index(cfg.index_path, cfg.corpus_path)
        questions = load_questions(args.questions)
    except (ConfigError, IndexError_, RecordError) as exc:
        print(f"sweep: error: {exc}", file=sys.stderr)
        return 1
    max_passages = args.max_passages or cfg.max_passages
    scored = score_questions(questions, index, cfg)
    # The engine's decision first, the side file only where the engine has
    # nothing to say. A corpus whose documents declare their own jurisdiction
    # no longer needs `layers.json` for this at all, and where both exist the
    # document's own claim is the one the engine actually retrieved on — so
    # reading the file over it would label a failure by a provenance the
    # answer did not use.
    layers = {**load_layers(Path(cfg.corpus_path)), **engine_layers(index)}

    answerable = sum(1 for s in scored if s.behavior == "answer")
    print(
        f"{len(scored)} questions ({answerable} answer, {len(scored) - answerable} refuse), "
        f"{sum(1 for s in scored if s.cross_language)} swept over corpus-scope candidates, "
        f"max_passages {max_passages}, layers {'known' if layers else 'unknown'} "
        f"({len(engine_layers(index))} from the index, "
        f"{len(load_layers(Path(cfg.corpus_path)))} from {LAYERS_FILE})"
    )
    print()
    grid = thresholds_range(args.start, args.stop, args.step)
    # The configured threshold is always a row, on the grid or not — it is
    # the one point on the curve the operator is actually standing on.
    grid = sorted(set(grid) | {round(cfg.threshold, 4)})
    rows = sweep(scored, grid, max_passages)
    print(render_curve(rows, cfg.threshold))
    if args.at is not None:
        print()
        print(render_at(scored, args.at, max_passages, layers))
    if args.json_out:
        payload = {
            "config": str(args.config),
            "questions": str(args.questions),
            "max_passages": max_passages,
            "configured_threshold": cfg.threshold,
            "curve": [
                {
                    "threshold": t,
                    "answer_rate": r.answer_rate,
                    "wrong_answer_rate": r.wrong_answer_rate,
                    **r.counts,
                }
                for t, r in rows
            ],
        }
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        print(f"\nCurve written to {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
