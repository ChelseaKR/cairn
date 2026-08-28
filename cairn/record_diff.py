"""Dry-run preview: what `cairn record` would write, diffed against the
committed bundle, without writing anything.

Reuses `record.build_items_and_responses` — the exact function `cairn record`
calls — so a diff here can never show something the real recorder would not
also produce. This is unscored, informational output only. It never says
"regression" or "fine", only "these items differ, and here is how": only the
pinned Plumbline harness, run through `./plumbline-gate.sh` and
`audit_guard.py`, gets to say pass or fail. Treating this as a substitute for
that gate is the one way to misuse it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.config import Config
from cairn.index import Index
from cairn.record import DEFAULT_QUESTIONS, build_items_and_responses, load_questions


@dataclass(frozen=True)
class ItemDiff:
    item_id: str
    kind: str  # "added" | "removed" | "changed"
    detail: str


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["id"]] = row
    return rows


def diff_against_bundle(
    index: Index,
    cfg: Config,
    bundle_dir: str | Path,
    *,
    questions_path: str | Path = DEFAULT_QUESTIONS,
) -> tuple[ItemDiff, ...]:
    bundle = Path(bundle_dir)
    old_responses = _read_jsonl(bundle / "responses.jsonl")
    old_items = _read_jsonl(bundle / "items.jsonl")

    questions = load_questions(questions_path)
    new_items, new_responses = build_items_and_responses(index, cfg, questions)
    new_responses_by_id = {r["id"]: r for r in new_responses}
    new_items_by_id = {i["id"]: i for i in new_items}

    old_ids, new_ids = set(old_responses), set(new_responses_by_id)
    diffs: list[ItemDiff] = []
    for item_id in sorted(new_ids - old_ids):
        diffs.append(ItemDiff(item_id, "added", "not in the committed bundle"))
    for item_id in sorted(old_ids - new_ids):
        diffs.append(
            ItemDiff(item_id, "removed", "no longer produced by this question set")
        )
    for item_id in sorted(old_ids & new_ids):
        old_text = old_responses[item_id]["response"]
        new_text = new_responses_by_id[item_id]["response"]
        old_sources = old_items.get(item_id, {}).get("sources", [])
        new_sources = new_items_by_id.get(item_id, {}).get("sources", [])
        changes = []
        if old_text != new_text:
            changes.append("response text differs")
        if old_sources != new_sources:
            changes.append(f"accepted sources differ: {old_sources} -> {new_sources}")
        if changes:
            diffs.append(ItemDiff(item_id, "changed", "; ".join(changes)))
    return tuple(diffs)


def render(diffs: tuple[ItemDiff, ...]) -> str:
    if not diffs:
        return (
            "No difference from the committed bundle. This is an unscored preview, "
            "not the gate — run ./plumbline-gate.sh for a real verdict."
        )
    lines = [f"{len(diffs)} item(s) differ from the committed bundle (unscored preview):"]
    lines += [f"  {d.kind:7} {d.item_id}: {d.detail}" for d in diffs]
    lines.append(
        "This is not a pass/fail verdict. Run `cairn record` and "
        "./plumbline-gate.sh for one."
    )
    return "\n".join(lines)
