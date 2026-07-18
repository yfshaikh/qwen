import importlib

import pytest

import engram.eval.checks  # noqa: F401  (registration)
from engram.eval.checks import (
    behavior,
    dedup,
    importance,
    integrity,
    lifecycle,
    recall_probes,
)
from engram.core.engram import Engram
from engram.core.models import LearningEvent
from engram.eval.registry import EvalContext, clear_registry, get_check, run_check
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture(autouse=True)
def _register_checks():
    # test_registry's autouse clear_registry() empties the registry when it runs
    # first in the same process; module-import caching won't re-fire @check. Reload
    # the check submodules so their decorators re-register for every test here.
    clear_registry()
    for mod in (dedup, importance, recall_probes, behavior, lifecycle, integrity):
        importlib.reload(mod)


def _node(id, label, forgotten=None, salience=0.9):
    return {"id": id, "label": label, "embedding": None,
            "forgotten_at": forgotten, "salience": salience,
            "mastery": 0.5, "confidence": 0.5}


def _snap(n, nodes, edges=None):
    return {"session": n, "sim_ts": "t", "report": {},
            "graph": {"nodes": nodes, "edges": edges or [], "evidence": {}}}


def _ctx(snapshots, params, eng=None, learner="L"):
    return EvalContext(eng=eng, scenario=None, learner_id=learner,
                       snapshots=snapshots, transcript=[], clock=None, params=params)


async def test_lifecycle_forgotten_kept_decayed():
    first = _snap(0, [_node("1", "Old Topic", salience=1.0), _node("2", "Fresh", salience=1.0)])
    last = _snap(1, [_node("1", "Old Topic", forgotten="2026-02-01", salience=0.01),
                     _node("2", "Fresh", salience=1.0)])
    params = {"expect": {"forgotten": ["Old Topic"], "kept": ["Fresh"],
                         "decayed": ["Old Topic"]}}
    res = await run_check(get_check("lifecycle"), _ctx([first, last], params))
    assert res.passed, res.details


async def test_lifecycle_decayed_missing_salience_fails_not_passes():
    # A None salience in either snapshot is a data bug, not decay — the old
    # `or 0.0` coercion reported a missing final salience as a (false) pass.
    first = _snap(0, [_node("1", "Topic", salience=0.9)])
    last = _snap(1, [_node("1", "Topic", salience=None)])
    params = {"expect": {"decayed": ["Topic"]}}
    res = await run_check(get_check("lifecycle"), _ctx([first, last], params))
    assert not res.passed
    assert any("salience missing" in d for d in res.details)


async def test_lifecycle_fails_on_missing_and_not_forgotten():
    last = _snap(0, [_node("1", "Still Here")])
    params = {"expect": {"forgotten": ["Still Here", "Never Existed"]}}
    res = await run_check(get_check("lifecycle"), _ctx([last], params))
    assert not res.passed
    joined = " ".join(res.details)
    assert "still live" in joined and "never existed" in joined


async def test_integrity_orphan_edge_and_idempotency():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=8))
    good = _snap(0, [_node("1", "A"), _node("2", "B")],
                 edges=[{"source": "1", "target": "2", "type": "relates_to", "weight": 1.0}])
    res = await run_check(get_check("integrity"), _ctx([good], {}, eng=eng))
    assert res.passed and res.metrics["orphan_edges"] == 0.0

    bad = _snap(0, [_node("1", "A")],
                edges=[{"source": "1", "target": "ghost", "type": "relates_to", "weight": 1.0}])
    res2 = await run_check(get_check("integrity"), _ctx([bad], {}, eng=eng))
    assert not res2.passed and res2.metrics["orphan_edges"] == 1.0


async def test_integrity_flags_unconsolidated_leftovers():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=8))
    await eng.ingest([LearningEvent(learner_id="L", type="utterance", text="hi")])
    snap = _snap(0, [])
    res = await run_check(get_check("integrity"), _ctx([snap], {}, eng=eng))
    assert not res.passed  # pending events after a run mean consolidation didn't drain


async def test_lifecycle_kept_matches_via_scenario_alias():
    # The concept survives under an abbreviated label; a declared alias lets the
    # 'kept' expectation pass (concept retention, not exact string).
    from types import SimpleNamespace
    last = _snap(0, [_node("1", "EM Induction")])
    params = {"expect": {"kept": ["Electromagnetic induction"]}}
    ctx = EvalContext(
        eng=None, scenario=SimpleNamespace(aliases={"Electromagnetic induction": ["EM Induction"]}),
        learner_id="L", snapshots=[last], transcript=[], clock=None, params=params)
    res = await run_check(get_check("lifecycle"), ctx)
    assert res.passed, res.details


async def test_lifecycle_kept_without_alias_still_fails():
    from types import SimpleNamespace
    last = _snap(0, [_node("1", "EM Induction")])
    params = {"expect": {"kept": ["Electromagnetic induction"]}}
    ctx = EvalContext(eng=None, scenario=SimpleNamespace(aliases={}), learner_id="L",
                      snapshots=[last], transcript=[], clock=None, params=params)
    res = await run_check(get_check("lifecycle"), ctx)
    assert not res.passed  # no alias -> abbreviation doesn't satisfy the full label


async def test_lifecycle_prefers_live_node_over_forgotten_alias_dup():
    # Concept appears twice: old forgotten node under the abbreviation, live node
    # under the canonical label. 'kept' must pass (live exists); 'forgotten' must
    # NOT falsely pass off the dead dup. Order: forgotten dup first in the list.
    from types import SimpleNamespace
    nodes = [_node("1", "EM Induction", forgotten="2026-02-01", salience=0.01),
             _node("2", "Electromagnetic Induction", salience=1.0)]
    last = _snap(0, nodes)
    scenario = SimpleNamespace(aliases={"Electromagnetic induction": ["EM Induction"]})

    kept = await run_check(get_check("lifecycle"), EvalContext(
        eng=None, scenario=scenario, learner_id="L", snapshots=[last],
        transcript=[], clock=None, params={"expect": {"kept": ["Electromagnetic induction"]}}))
    assert kept.passed, kept.details

    forgot = await run_check(get_check("lifecycle"), EvalContext(
        eng=None, scenario=scenario, learner_id="L", snapshots=[last],
        transcript=[], clock=None, params={"expect": {"forgotten": ["Electromagnetic induction"]}}))
    assert not forgot.passed  # a live variant exists -> concept is NOT forgotten
