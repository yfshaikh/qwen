"""Config sweeps. Tier-1 re-scores a frozen graph (recall weights only, cheap).
Tier-2 rebuilds the graph from the transcript (Keeper params; LLM in the loop)."""
from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from itertools import combinations
from typing import Any

from engram.core.models import LearningEvent
from engram.core.recall import RecallWeights, cosine_similarity
from engram.core.text import normalize_label
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


async def rebuild_graph_from_sessions(
    eng: Any, sessions: list[dict], learner_id: str, *, clock: Any = None
) -> None:
    """Ingest + consolidate each fixture session, advancing `clock` by gap_days.

    Lets Tier-2 actually exercise decay/prune and cross-session cosine merges
    (tmp- nodes from prior sessions become real ids after consolidate).
    """
    role_to_type = {"user": "utterance", "assistant": "tutor_explanation"}
    for session in sessions:
        gap = float(session.get("gap_days") or 0.0)
        if gap and clock is not None:
            clock.advance(days=gap)
        turns = session.get("turns") or []
        events = [
            LearningEvent(learner_id=learner_id, type=role_to_type[t["role"]], text=t["content"])
            for t in turns if t.get("role") in role_to_type
        ]
        if events:
            await eng.ingest(events)
            await eng.consolidate(learner_id)


async def rebuild_graph_from_transcript(
    eng: Any, transcript_turns: list[dict], learner_id: str
) -> None:
    await rebuild_graph_from_sessions(eng, [{"turns": transcript_turns}], learner_id)


async def _duplicate_label_rate(storage: Any, learner_id: str) -> float:
    nodes = await storage.get_live_nodes(learner_id)
    pairs = list(combinations(nodes, 2))
    if not pairs:
        return 0.0
    dup = sum(
        1 for a, b in pairs
        if normalize_label(a.label) == normalize_label(b.label)
        or (a.embedding and b.embedding
            and cosine_similarity(a.embedding, b.embedding) > 0.92))
    return dup / len(pairs)


async def run_tier2_sweep(
    eng: Any, sessions: list[dict], probes: list[Probe], grid: dict[str, list],
    *, target: str = "node_hit_rate", clock: Any = None,
) -> dict[str, Any]:
    """Rebuild the graph from the fixture transcript per grid point, so Keeper
    params (tau_high/tau_low/decay/...) are live. LLM in the loop — costs money
    with a real provider. Sessions are consolidated one-by-one with SimClock
    gaps so decay and cross-session merges are reachable.
    """
    from engram.core.engram import Engram
    from engram.eval.clock import SimClock

    rows: list[dict] = []
    run_id = uuid.uuid4().hex[:8]
    for i, combo in enumerate(expand_grid(grid)):
        learner_id = f"eval:sweep2:{run_id}:{i}"
        settings = eng.settings.model_copy(update=combo) if eng.settings is not None else None
        sess_clock = SimClock()  # fresh per combo; `clock` arg unused (API compat)
        eng2 = Engram(storage=eng.storage, llm=eng.llm, embedder=eng.embedder,
                      settings=settings, now=sess_clock)
        try:
            await rebuild_graph_from_sessions(eng2, sessions, learner_id, clock=sess_clock)
            defaults = (RecallWeights(settings.recall_w_recency, settings.recall_w_importance,
                                      settings.recall_w_relevance)
                        if settings is not None else RecallWeights())
            weights = weights_from_combo(combo, defaults)
            arm_kw = {k.replace("recall_", "").replace("default_budget", "budget"): combo[k]
                      for k in _ARM_KEYS if k in combo}
            scored = await run_recall_arm(eng.storage, eng.embedder, learner_id,
                                          probes, weights, **arm_kw)
            metrics = aggregate_recall([s for _, s in scored])
            metrics["duplicate_label_rate"] = await _duplicate_label_rate(
                eng.storage, learner_id)
        finally:
            await eng.storage.delete_learner(learner_id)
        rows.append({**combo, **metrics})
    best = max(rows, key=lambda r: r[target]) if rows else {}
    return {"rows": rows, "best": best}
