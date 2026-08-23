"""The gauntlet target adapter: Cairn's engine, wearing an evaluation harness.

This module is the interlock's hinge, and it deliberately lives on the
harness side of the dependency line: it imports nothing from the pinned
harness at module scope that the core path would need, and the harness
imports *it* through ``--callable gauntlet_target:make_target``. The core
install/lint/test path never touches gauntlet, exactly as it never touches
plumbline.

The adapter answers with :class:`~gauntlet.targets.TargetResponse` fields
derived from one place — :func:`cairn.engine.ask` — so what gauntlet grades
is what the CLI and the served interface serve:

- ``text`` is ``Answer.cited_text``: notice, quotes, inline markers. A gate
  checking "every factual answer carries a source identifier" grades the
  same string a terminal client receives.
- ``citations`` are the quoted sources' ids; ``context_ids`` are every source
  retrieval accepted (composition's choice set), which is the honest reading
  of "the context the target reports retrieving".
- ``refused`` mirrors ``kind == "refusal"``; Cairn has no escalation concept,
  so ``escalated`` is always False and no crisis case may be authored against
  this target until one exists.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# The harness runs from its own checkout, so every relative path in the
# config would resolve wrong. The adapter pins paths to *this* repository:
# it is Cairn's engine, at this tree's commit, that is under evaluation.
ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _engine():
    from cairn.config import Config
    from cairn.engine import ask
    from cairn.index import build_index

    cfg = Config()
    index = build_index(ROOT / cfg.corpus_path)

    def answer(prompt: str, language: str):
        result = ask(prompt, index, cfg, lang=language or None)
        a = result.answer
        cited_ids = tuple(s.source_id for s in a.sources)
        context_ids = tuple(
            c.passage.passage_id for t in result.attempts for c in t.trace.accepted
        ) or cited_ids
        from gauntlet.targets import TargetResponse

        return TargetResponse(
            text=a.cited_text,
            citations=cited_ids,
            context_ids=context_ids,
            refused=a.kind == "refusal",
            escalated=False,
        )

    return answer


def make_target():
    """Factory named by ``gauntlet run --callable gauntlet_target:make_target``."""
    from gauntlet.targets import CallableTarget

    def provenance() -> dict[str, str]:
        from cairn import __version__
        from cairn.config import Config
        from cairn.corpus import fingerprint

        return {
            "target": "cairn",
            "version": __version__,
            "corpus_fingerprint": fingerprint(ROOT / Config().corpus_path),
        }

    return CallableTarget(fn=_engine(), name="cairn", provenance_fn=provenance)
