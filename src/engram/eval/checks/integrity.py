from __future__ import annotations

import math

from engram.eval.registry import CheckResult, EvalContext, check

_BOUNDED = ("mastery", "confidence", "salience")


@check("integrity")
async def integrity(ctx: EvalContext) -> CheckResult:
    g = ctx.snapshots[-1]["graph"] if ctx.snapshots else {"nodes": [], "edges": []}
    ids = {n["id"] for n in g["nodes"]}
    failures: list[str] = []

    orphans = [e for e in g["edges"] if e["source"] not in ids or e["target"] not in ids]
    failures += [f"orphan edge {e['source']}->{e['target']}" for e in orphans]

    for n in g["nodes"]:
        for f in _BOUNDED:
            v = n.get(f)
            if v is None:
                continue
            if isinstance(v, float) and math.isnan(v):
                failures.append(f"node {n['label']!r}: {f} is NaN")
            elif not (0.0 <= v <= 1.0):
                failures.append(f"node {n['label']!r}: {f}={v} outside [0,1]")

    # Drain + idempotency. NB: check pending events DIRECTLY — a failed
    # extraction leaves events pending while reporting processed_events=0, so
    # the consolidate probe alone would miss it.
    if ctx.eng is not None:
        pending = await ctx.eng.storage.get_pending_events(ctx.learner_id)
        if pending:
            failures.append(f"{len(pending)} unconsolidated events remain after run")
        report = await ctx.eng.consolidate(ctx.learner_id)
        processed = getattr(report, "processed_events", 0)
        if not pending and processed:
            failures.append(f"consolidate not idempotent: reprocessed {processed} events")

    return CheckResult(
        name="integrity",
        metrics={"orphan_edges": float(len(orphans)),
                 "integrity_failures": float(len(failures))},
        passed=not failures, details=failures)
