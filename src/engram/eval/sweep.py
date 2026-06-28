"""Config sweeps. Tier-1 re-scores a frozen graph (recall weights only, cheap).
Tier-2 rebuilds the graph from the transcript (Keeper params; LLM in the loop)."""
from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from typing import Any

from engram.core.models import LearningEvent
from engram.core.recall import RecallWeights
from engram.eval.arms import run_recall_arm
from engram.eval.fixtures import load_graph_into
from engram.eval.metrics import aggregate_recall
from engram.eval.scenario import Probe

_WEIGHT_KEYS = {
    "recall_w_recency": "recency",
    "recall_w_importance": "importance",
    "recall_w_relevance": "relevance",
}
_ARM_KEYS = ("recall_seed_k", "recall_hops", "recall_fanout", "recall_default_budget")


def expand_grid(grid: dict[str, list]) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def weights_from_combo(combo: dict, defaults: RecallWeights) -> RecallWeights:
    over = {attr: combo[key] for key, attr in _WEIGHT_KEYS.items() if key in combo}
    return replace(defaults, **over)


async def run_tier1_sweep(
    storage: Any, embedder: Any, graph: dict, probes: list[Probe], grid: dict[str, list],
    *, target: str = "node_hit_rate", defaults: RecallWeights | None = None,
) -> dict[str, Any]:
    defaults = defaults or RecallWeights()
    rows: list[dict] = []
    run_id = uuid.uuid4().hex[:8]
    for i, combo in enumerate(expand_grid(grid)):
        learner_id = f"eval:sweep:{run_id}:{i}"
        await load_graph_into(storage, graph, learner_id)
        try:
            weights = weights_from_combo(combo, defaults)
            arm_kw = {k.replace("recall_", "").replace("default_budget", "budget"): combo[k]
                      for k in _ARM_KEYS if k in combo}
            scored = await run_recall_arm(storage, embedder, learner_id, probes, weights, **arm_kw)
            metrics = aggregate_recall([s for _, s in scored])
        finally:
            await storage.delete_learner(learner_id)
        rows.append({**combo, **metrics})
    best = max(rows, key=lambda r: r[target]) if rows else {}
    return {"rows": rows, "best": best}


async def rebuild_graph_from_transcript(
    eng: Any, transcript_turns: list[dict], learner_id: str
) -> None:
    role_to_type = {"user": "utterance", "assistant": "tutor_explanation"}
    events = [LearningEvent(learner_id=learner_id, type=role_to_type[t["role"]], text=t["content"])
              for t in transcript_turns if t["role"] in role_to_type]
    await eng.ingest(events)
    await eng.consolidate(learner_id)
