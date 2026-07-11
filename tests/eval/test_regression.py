from engram.eval.regression import compare, flatten_metrics


def test_compare_directions_and_tolerance():
    base = {"node_hit_rate": 0.9, "mean_rank": 1.5, "usd": 0.10}
    cur_ok = {"node_hit_rate": 0.95, "mean_rank": 1.2, "usd": 0.10}
    assert compare(cur_ok, base) == []

    cur_bad = {"node_hit_rate": 0.7, "mean_rank": 3.0, "usd": 0.10}
    regs = {r["metric"] for r in compare(cur_bad, base)}
    assert regs == {"node_hit_rate", "mean_rank"}

    cur_within = {"node_hit_rate": 0.89, "mean_rank": 1.5, "usd": 0.10}
    assert compare(cur_within, base, tolerance=0.02) == []


def test_flatten_metrics_collision_prefix():
    run = {"cost": {"usd": 0.5},
           "checks": [{"name": "a", "metrics": {"x": 1.0}},
                      {"name": "b", "metrics": {"x": 2.0, "y": 3.0}}]}
    flat = flatten_metrics(run)
    assert flat == {"x": 1.0, "b.x": 2.0, "y": 3.0, "usd": 0.5}
