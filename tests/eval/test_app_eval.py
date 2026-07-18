import asyncio
import importlib

import httpx
import pytest
from httpx import ASGITransport

import engram.eval.checks  # noqa: F401  (registration)
from engram.app.deps import get_engram
from engram.app.main import app, _eval_tasks
from engram.core.engram import Engram
from engram.eval.checks import (
    behavior,
    dedup,
    importance,
    integrity,
    lifecycle,
    recall_probes,
)
from engram.eval.registry import clear_registry
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage

EXTRACTION = (
    '{"concepts": [{"label": "Limits", "summary": "s",'
    ' "evidence": [{"kind": "asked_about", "content": "q"}]}],'
    ' "preferences": [], "goals": [], "relations": []}'
)


@pytest.fixture(autouse=True)
def _register_checks():
    # test_registry's autouse clear_registry() empties the registry when it runs
    # first in the same process; import caching won't re-fire @check. Reload the
    # check submodules so their decorators re-register for the launch test's run.
    clear_registry()
    for mod in (dedup, importance, recall_probes, behavior, integrity, lifecycle):
        importlib.reload(mod)


class _S:  # minimal settings stand-in: eval endpoints read only these fields
    eval_ui = True
    eval_price_in_per_m = 0.0
    eval_price_out_per_m = 0.0
    # recall fields used by Engram.recall when settings is not None:
    recall_w_recency = 0.3
    recall_w_importance = 0.3
    recall_w_relevance = 0.4
    recall_seed_k = 8
    recall_hops = 2
    recall_fanout = 10
    recall_default_budget = 800
    recall_session_buffer = True
    keeper_tau_high = 0.86
    keeper_tau_low = 0.72
    keeper_ewma_alpha = 0.3
    keeper_salience_bump = 0.3
    keeper_prune_floor = 0.05
    recall_decay = 0.98
    recall_history_turns = 10


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text=EXTRACTION),
               embedder=FakeEmbedder(dim=64), settings=_S())
    app.dependency_overrides[get_engram] = lambda: e
    _eval_tasks.clear()
    yield e
    app.dependency_overrides.clear()
    _eval_tasks.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_flag_off_404s(eng):
    eng.settings.eval_ui = False
    async with _client() as c:
        assert (await c.get("/eval/runs")).status_code == 404


async def test_scenarios_listed(eng):
    async with _client() as c:
        r = await c.get("/eval/scenarios")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["scenarios"]]
    assert "calc-mastery" in ids


async def test_launch_run_and_single_flight(eng, tmp_path, monkeypatch):
    import engram.app.main as m
    monkeypatch.setattr(m, "_RUNS_BASE", tmp_path)      # redirect run store to tmp
    async with _client() as c:
        # single-flight: a live in-flight task must block a new launch -> 409.
        # (A real fake-backed run finishes in ~3ms without ever yielding to the
        # loop, so we assert the guard against a deterministically-alive sentinel
        # instead of racing the run to completion.)
        live = asyncio.create_task(asyncio.Event().wait())
        _eval_tasks["sentinel"] = live
        assert (await c.post("/eval/runs", json={"scenario_id": "calc-mastery"})).status_code == 409
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass
        _eval_tasks.clear()

        # with no run alive, a launch succeeds and runs to completion
        r = await c.post("/eval/runs", json={"scenario_id": "calc-mastery"})
        assert r.status_code == 202
        d = r.json()["dir"]
        for t in list(_eval_tasks.values()):
            await t  # drain
        detail = await c.get(f"/eval/runs/{d}")
        assert detail.status_code == 200
        assert detail.json()["status"] in ("passed", "failed")
        runs = await c.get("/eval/runs")
        assert runs.json()["runs"][0]["alive"] is False


async def test_unknown_scenario_404_and_traversal_guard(eng):
    async with _client() as c:
        assert (await c.post("/eval/runs", json={"scenario_id": "nope"})).status_code == 404
        assert (await c.get("/eval/runs/..%2Fsecret")).status_code == 404


def test_run_dir_rejects_bare_dot_segments():
    # httpx normalizes "." / ".." away client-side (RFC 3986), so they can't be
    # exercised through the ASGI client — but a raw socket can send them and
    # Starlette does NOT normalize. Test the guard function directly.
    from fastapi import HTTPException

    from engram.app.main import _run_dir

    for name in (".", ".."):
        with pytest.raises(HTTPException) as e:
            _run_dir(name)
        assert e.value.status_code == 404
