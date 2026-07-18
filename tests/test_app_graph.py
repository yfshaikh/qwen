import httpx
import pytest
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from engram.core.models import Edge, EdgeType, Node, NodeType
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder())
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_graph_returns_nodes_edges(eng):
    a = await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0, 0.0])
    )
    b = await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="B", embedding=[0.0, 1.0])
    )
    await eng.storage.insert_edge(
        Edge(learner_id="a", source_id=a, target_id=b, type=EdgeType.PREREQUISITE)
    )
    async with _client() as c:
        r = await c.get("/graph", params={"learner_id": "a"})
    assert r.status_code == 200
    body = r.json()
    assert sorted(n["label"] for n in body["nodes"]) == ["A", "B"]
    assert body["edges"][0]["type"] == "prerequisite"


async def test_graph_focus_filters(eng):
    a = await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0, 0.0])
    )
    await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Isolated", embedding=[0.5, 0.5])
    )
    async with _client() as c:
        r = await c.get("/graph", params={"learner_id": "a", "focus": a})
    assert [n["label"] for n in r.json()["nodes"]] == ["A"]  # focus node has no neighbors


async def test_graph_requires_learner_id(eng):
    async with _client() as c:
        r = await c.get("/graph")
    assert r.status_code == 422
