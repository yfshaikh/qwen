"""Tier-2 sweep rebuilds the graph per grid point (Keeper params in the loop)."""
import json

from engram.app.config import Settings
from engram.core.engram import Engram
from engram.core.models import Completion, Message
from engram.eval.clock import SimClock
from engram.eval.scenario import Probe
from engram.eval.sweep import rebuild_graph_from_sessions, run_tier2_sweep
from tests.fakes import FakeEmbedder, FakeStorage

EXTRACTION = json.dumps({
    "concepts": [{"label": "Flux", "summary": "s", "importance": 0.8,
                  "evidence": [{"kind": "asked_about", "content": "q"}]}],
    "preferences": [], "goals": [], "relations": [],
})


class _LLM:
    async def complete(self, role: str, messages: list[Message], schema=None) -> Completion:
        return Completion(text=EXTRACTION if role == "extractor" else "no")


def _settings(**over):
    base = dict(
        dashscope_api_key="k", database_url="d",
        model_tutor="m", model_extractor="m", model_reflector="m", model_embedder="m",
    )
    return Settings(_env_file=None, **base, **over)


SESSIONS = [{"turns": [
    {"role": "user", "content": "what is magnetic flux?"},
    {"role": "assistant", "content": "flux measures field through a surface"},
]}]


async def test_tier2_rebuilds_per_combo_and_cleans_up():
    storage = FakeStorage()
    eng = Engram(storage=storage, llm=_LLM(), embedder=FakeEmbedder(dim=8),
                 settings=_settings())
    grid = {"keeper_tau_high": [0.7, 0.9], "recall_w_relevance": [0.4]}
    out = await run_tier2_sweep(
        eng, SESSIONS, [Probe(query="flux", expect_nodes=["Flux"])], grid)
    assert len(out["rows"]) == 2
    for row in out["rows"]:
        assert "keeper_tau_high" in row
        assert "node_hit_rate" in row
        assert "duplicate_label_rate" in row
    assert out["best"]
    # every sweep learner deleted
    assert await storage.get_live_nodes("L") == []
    assert all(not n.learner_id.startswith("eval:sweep2")
               for n in storage.nodes.values())


async def test_rebuild_advances_clock_and_consolidates_per_session():
    storage = FakeStorage()
    clock = SimClock()
    eng = Engram(storage=storage, llm=_LLM(), embedder=FakeEmbedder(dim=8),
                 settings=_settings(), now=clock)
    consolidations: list = []
    orig = eng.consolidate

    async def _track(learner_id):
        consolidations.append(clock())
        return await orig(learner_id)

    eng.consolidate = _track  # type: ignore[method-assign]
    sessions = [
        {"turns": [{"role": "user", "content": "flux?"},
                   {"role": "assistant", "content": "field through a surface"}],
         "gap_days": 0},
        {"turns": [{"role": "user", "content": "faraday?"},
                   {"role": "assistant", "content": "emf from flux change"}],
         "gap_days": 10},
    ]
    await rebuild_graph_from_sessions(eng, sessions, "L", clock=clock)
    assert len(consolidations) == 2
    assert (consolidations[1] - consolidations[0]).days == 10
    live = await storage.get_live_nodes("L")
    assert live  # graph survived both sessions
