import importlib

import pytest

import engram.eval.checks  # noqa: F401
from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from engram.eval.checks import behavior, dedup, importance, recall_probes
from engram.eval.registry import EvalContext, clear_registry, get_check, run_check
from engram.eval.scenario import Probe, Scenario
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture(autouse=True)
def _register_checks():
    clear_registry()
    for mod in (dedup, importance, recall_probes, behavior):
        importlib.reload(mod)


def _scenario(probes):
    return Scenario(id="t", persona="", hidden_state={}, sessions=[], probes=probes)


async def test_recall_probes_check_hits():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=1024))
    await eng.storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT,
                                       label="Limits", salience=0.9, embedding=[1.0] * 1024))
    sc = _scenario([Probe(query="limits", expect_nodes=["Limits"])])
    ctx = EvalContext(eng=eng, scenario=sc, learner_id="L", snapshots=[],
                      transcript=[], clock=None, params={})
    res = await run_check(get_check("recall_probes"), ctx)
    assert res.metrics["node_hit_rate"] == 1.0 and res.passed
