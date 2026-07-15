"""Golden wire-shape guard (arch-remediation Task 0).

Pins the sorted JSON key-set of every HTTP response (and, for list
responses, the item key-set) so later refactor tasks cannot silently
change the wire. This test documents the CURRENT shape — it is expected
to PASS immediately. A task that has to edit this file is changing the
wire and must justify it.
"""
import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.consolidation import AuditEntry, ConsolidationPlan, MasteryPoint
from engram.core.engram import Engram
from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)
from engram.runtime.host import EngramHost
from engram.integrations.fastapi import memory_router
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage

LEARNER = "L"


async def _seed(storage: FakeStorage) -> None:
    """One learner: two nodes, a prerequisite edge, an evidence row, an
    audit row (via apply_consolidation), and a mastery-history row."""
    storage.nodes["a"] = Node(
        id="a", learner_id=LEARNER, type=NodeType.CONCEPT, label="Algebra",
        mastery=0.3, confidence=0.5, salience=0.2, importance=0.9,
    )
    storage.nodes["b"] = Node(
        id="b", learner_id=LEARNER, type=NodeType.CONCEPT, label="Geometry",
        mastery=0.8, confidence=0.6, salience=0.9, importance=0.5,
    )
    storage.edges.append(Edge(
        id="e1", learner_id=LEARNER, source_id="a", target_id="b",
        type=EdgeType.PREREQUISITE, weight=1.0,
    ))
    storage.evidence.append(Evidence(
        id="ev1", node_id="a", kind=EvidenceKind.STRUGGLE,
        content="struggled with factoring", importance=0.5,
    ))
    await storage.insert_event(LearningEvent(
        learner_id=LEARNER, type="quiz_wrong", text="ate my homework",
    ))
    await storage.apply_consolidation(ConsolidationPlan(
        learner_id=LEARNER,
        mastery_history=[MasteryPoint(node_id="a", mastery=0.3, confidence=0.5)],
        audit=[AuditEntry(op="merge", rationale="r")],
    ))


def _client(storage):
    eng = Engram(storage=storage, llm=FakeLLM(), embedder=FakeEmbedder())
    app.dependency_overrides[get_engram] = lambda: eng
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


_GRAPH_NODE_KEYS = ["confidence", "evidence", "id", "importance", "label",
                    "mastery", "salience", "summary", "type"]
_GRAPH_EDGE_KEYS = ["id", "source", "target", "type", "weight"]


async def test_graph_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/graph", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["edges", "nodes"]
        assert body["nodes"], "expected at least one node in the seeded graph"
        assert body["edges"], "expected at least one edge in the seeded graph"
        assert sorted(body["nodes"][0]) == _GRAPH_NODE_KEYS
        assert sorted(body["edges"][0]) == _GRAPH_EDGE_KEYS
    finally:
        app.dependency_overrides.clear()


async def test_audit_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/audit", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["cursor", "rows"]
        assert body["rows"], "expected at least one audit row"
        assert sorted(body["rows"][0]) == [
            "cost", "id", "model", "op", "rationale", "tokens", "ts"]
    finally:
        app.dependency_overrides.clear()


_RECALL_NODE_KEYS = ["confidence", "evidence", "id", "importance", "label",
                     "mastery", "salience", "score", "scores", "type"]
_RECALL_EDGE_KEYS = ["id", "source", "target", "type", "weight"]
_RECALL_SCORES_KEYS = ["importance", "recency", "relevance"]


async def test_recall_wire_shape():
    s = FakeStorage()
    await _seed(s)
    # Give the seeded nodes embeddings so vector_search seeds them: FakeEmbedder
    # produces a query vector of [len(query) % 7] * dim (all components equal),
    # which is cosine-parallel to any other nonzero constant-valued vector — so
    # any nonzero embedding here guarantees both nodes are selected as seeds.
    s.nodes["a"].embedding = [1.0] * 1024
    s.nodes["b"].embedding = [1.0] * 1024
    try:
        async with _client(s) as c:
            r = await c.post(
                "/recall",
                json={"learner_id": LEARNER, "query": "algebra help", "budget": 800},
            )
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["subgraph", "text_block"]
        subgraph = body["subgraph"]
        assert sorted(subgraph) == ["edges", "nodes"]
        assert subgraph["nodes"], "expected at least one node in the recall subgraph"
        assert subgraph["edges"], "expected at least one edge in the recall subgraph"
        assert sorted(subgraph["nodes"][0]) == _RECALL_NODE_KEYS
        assert sorted(subgraph["nodes"][0]["scores"]) == _RECALL_SCORES_KEYS
        assert sorted(subgraph["edges"][0]) == _RECALL_EDGE_KEYS
    finally:
        app.dependency_overrides.clear()


async def test_insights_summary_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/summary", params={"learner_id": LEARNER})
        assert r.status_code == 200
        assert sorted(r.json()) == [
            "avg_confidence", "avg_mastery", "concepts", "edges", "evidence",
            "fading", "forgotten", "last_active", "open_misconceptions", "sessions"]
    finally:
        app.dependency_overrides.clear()


async def test_insights_mastery_timeline_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/mastery-timeline", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["series"]
        assert body["series"], "expected at least one series"
        points = next(iter(body["series"].values()))
        assert points, "expected at least one mastery point"
        assert sorted(points[0]) == ["confidence", "mastery", "ts"]
    finally:
        app.dependency_overrides.clear()


async def test_insights_hotspots_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/hotspots", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["hotspots"]
        assert body["hotspots"], "expected at least one hotspot"
        assert sorted(body["hotspots"][0]) == [
            "label", "mastery", "node_id", "struggle", "trend"]
    finally:
        app.dependency_overrides.clear()


async def test_insights_activity_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/activity", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["days"]
        assert body["days"], "expected at least one activity day"
        assert sorted(body["days"][0]) == ["count", "day"]
    finally:
        app.dependency_overrides.clear()


async def test_insights_review_queue_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/review-queue", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["items"]
        assert body["items"], "expected at least one review-queue item"
        assert sorted(body["items"][0]) == ["label", "node_id", "reason", "score"]
    finally:
        app.dependency_overrides.clear()


async def test_insights_blockers_wire_shape():
    s = FakeStorage()
    await _seed(s)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/blockers", params={"learner_id": LEARNER})
        assert r.status_code == 200
        body = r.json()
        assert sorted(body) == ["blockers"]
        assert body["blockers"], "expected at least one blocker"
        assert sorted(body["blockers"][0]) == ["label", "mastery", "node_id", "path"]
    finally:
        app.dependency_overrides.clear()


# --- memory_router (mounted like tests/test_integrations_fastapi.py) -------

async def _host():
    storage = FakeStorage()
    await _seed(storage)
    host = EngramHost(Engram(storage=storage, llm=FakeLLM(), embedder=FakeEmbedder(dim=8)))
    await host.start()
    return host


def _memory_app(host):
    memapp = FastAPI()

    async def learner_id_dep() -> str:
        return LEARNER

    memapp.include_router(memory_router(lambda: host, learner_id_dep=learner_id_dep))
    return memapp


async def test_memory_graph_wire_shape():
    host = await _host()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_memory_app(host)), base_url="http://t"
    ) as c:
        r = await c.get("/memory/graph")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body) == ["edges", "enabled", "nodes"]
    assert body["nodes"], "expected at least one node"
    assert body["edges"], "expected at least one edge"
    assert sorted(body["nodes"][0]) == _GRAPH_NODE_KEYS
    assert sorted(body["edges"][0]) == _GRAPH_EDGE_KEYS


async def test_memory_status_wire_shape():
    host = await _host()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_memory_app(host)), base_url="http://t"
    ) as c:
        r = await c.get("/memory/status")
    assert r.status_code == 200
    assert sorted(r.json()) == ["consolidating"]
