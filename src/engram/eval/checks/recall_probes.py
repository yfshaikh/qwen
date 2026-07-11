from __future__ import annotations

from engram.core.recall import RecallWeights
from engram.eval.arms import run_recall_arm
from engram.eval.metrics import aggregate_recall
from engram.eval.registry import CheckResult, EvalContext, check


@check("recall_probes")
async def recall_probes(ctx: EvalContext) -> CheckResult:
    s = getattr(ctx.eng, "settings", None)
    if s is not None:
        weights = RecallWeights(s.recall_w_recency, s.recall_w_importance, s.recall_w_relevance)
        kw = dict(seed_k=s.recall_seed_k, hops=s.recall_hops, fanout=s.recall_fanout,
                  budget=s.recall_default_budget)
    else:
        weights, kw = RecallWeights(), {}
    scored = await run_recall_arm(ctx.eng.storage, ctx.eng.embedder, ctx.learner_id,
                                  ctx.scenario.probes, weights, **kw)
    metrics = aggregate_recall([sc for _, sc in scored])
    details = [f"probe {sc.query!r}: missing {sc.missing}" for _, sc in scored if sc.missing]
    return CheckResult(name="recall_probes", metrics=metrics,
                       passed=metrics["node_hit_rate"] >= float(ctx.param("min_hit_rate", 0.5)),
                       details=details)
