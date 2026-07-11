from __future__ import annotations

from engram.eval.arms import run_behavior_arm
from engram.eval.metrics import aggregate_behavior, judge_turn
from engram.eval.registry import CheckResult, EvalContext, check


@check("behavior", needs="live")
async def behavior(ctx: EvalContext) -> CheckResult:
    """ON vs baseline replay + LLM judge. Spends LLM calls: only runs when the
    scenario names it. Informational unless max_re_explanation_rate is set."""
    turns = [t["content"] for t in ctx.transcript if t["role"] == "user"]
    on = await run_behavior_arm(ctx.eng, turns, ctx.learner_id, "on")
    base = await run_behavior_arm(ctx.eng, turns, ctx.learner_id, "baseline")
    on_m = aggregate_behavior(
        [await judge_turn(ctx.eng.llm, r, ctx.scenario.hidden_state) for r in on])
    base_m = aggregate_behavior(
        [await judge_turn(ctx.eng.llm, r, ctx.scenario.hidden_state) for r in base])
    metrics = {f"on_{k}": v for k, v in on_m.items()}
    metrics |= {f"baseline_{k}": v for k, v in base_m.items()}
    cap = ctx.param("max_re_explanation_rate")
    passed = True if cap is None else on_m["re_explanation_rate"] <= float(cap)
    return CheckResult(name="behavior", metrics=metrics, passed=passed,
                       details=[f"ON {on_m} vs BASE {base_m}"])
