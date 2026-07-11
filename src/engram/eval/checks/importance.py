from __future__ import annotations

from engram.eval.registry import CheckResult, EvalContext, check


@check("importance")
async def importance(ctx: EvalContext) -> CheckResult:
    g = ctx.snapshots[-1]["graph"]
    nodes = [n for n in g["nodes"] if not n.get("forgotten_at")]
    ev = g.get("evidence", {})

    def covered(n: dict) -> bool:
        if n.get("importance") is not None:  # spec-2's node column, when it lands
            return True
        return any(e.get("importance") is not None for e in ev.get(n["id"], []))

    cov = sum(1 for n in nodes if covered(n)) / len(nodes) if nodes else 0.0
    missing = [n["label"] for n in nodes if not covered(n)]
    # threshold default 0.0: informational until spec 2 makes importance real.
    return CheckResult(name="importance", metrics={"importance_coverage": cov},
                       passed=cov >= ctx.threshold(0.0),
                       details=[f"no importance: {m}" for m in missing[:10]])
