import importlib

import pytest

import engram.eval.checks  # noqa: F401  (registration)
from engram.eval.checks import behavior, dedup, importance, recall_probes
from engram.eval.registry import EvalContext, clear_registry, get_check, run_check


@pytest.fixture(autouse=True)
def _register_checks():
    # test_registry's autouse clear_registry() empties the registry when it runs
    # first in the same process; module-import caching won't re-fire @check. Reload
    # the check submodules so their decorators re-register for every test here.
    clear_registry()
    for mod in (dedup, importance, recall_probes, behavior):
        importlib.reload(mod)


def _snap(nodes, evidence=None):
    return {"session": 0, "sim_ts": "t", "report": {},
            "graph": {"nodes": nodes, "edges": [], "evidence": evidence or {}}}


def _ctx(nodes, evidence=None, params=None):
    return EvalContext(eng=None, scenario=None, learner_id="x",
                       snapshots=[_snap(nodes, evidence)], transcript=[],
                       clock=None, params=params or {})


async def test_dedup_flags_normalized_duplicates():
    nodes = [
        {"id": "1", "label": "NMOS Transistor", "embedding": None, "forgotten_at": None},
        {"id": "2", "label": "nmos transistors", "embedding": None, "forgotten_at": None},
        {"id": "3", "label": "Ohm's Law", "embedding": None, "forgotten_at": None},
        {"id": "4", "label": "Gone", "embedding": None, "forgotten_at": "2026-01-01"},
    ]
    res = await run_check(get_check("dedup"), _ctx(nodes))
    # 3 live nodes -> 3 pairs, 1 duplicate pair
    assert res.metrics["duplicate_label_rate"] == 1 / 3
    assert res.passed is False and any("NMOS" in d for d in res.details)


async def test_dedup_small_graph_passes():
    res = await run_check(get_check("dedup"),
                          _ctx([{"id": "1", "label": "A", "embedding": None, "forgotten_at": None}]))
    assert res.metrics["duplicate_label_rate"] == 0.0 and res.passed


async def test_importance_coverage():
    nodes = [{"id": "1", "label": "A", "embedding": None, "forgotten_at": None, "importance": 0.7},
             {"id": "2", "label": "B", "embedding": None, "forgotten_at": None}]
    ev = {"2": [{"kind": "note", "content": "c", "importance": None}]}
    res = await run_check(get_check("importance"), _ctx(nodes, ev))
    assert res.metrics["importance_coverage"] == 0.5
    assert res.passed  # default threshold 0.0 -> informational
