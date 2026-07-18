"""Metric-direction-aware comparison of two runs (the CI hook)."""
from __future__ import annotations

LOWER_BETTER = {
    "mean_rank", "mastered_leak_rate", "duplicate_label_rate",
    "on_re_explanation_rate", "baseline_re_explanation_rate",
    "lifecycle_failures", "integrity_failures", "orphan_edges", "usd",
}


def flatten_metrics(run: dict) -> dict[str, float]:
    flat: dict[str, float] = {}
    for c in run.get("checks", []):
        for k, v in (c.get("metrics") or {}).items():
            flat[k if k not in flat else f"{c['name']}.{k}"] = v
    usd = (run.get("cost") or {}).get("usd")
    if usd is not None:
        flat["usd"] = usd
    return flat


def compare(current: dict[str, float], baseline: dict[str, float],
            tolerance: float = 0.0) -> list[dict]:
    regressions = []
    for metric, base_v in baseline.items():
        if metric not in current:
            continue
        cur_v = current[metric]
        worse = (cur_v - base_v) if metric in LOWER_BETTER else (base_v - cur_v)
        if worse > tolerance:
            regressions.append({"metric": metric, "current": cur_v,
                                "baseline": base_v, "delta": worse})
    return regressions
