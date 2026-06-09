"""End-to-end app tests using fakes injected via dependency_overrides — no DB,
no network. The lifespan's real composition is monkeypatched to a no-op."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from engram.adapters.host.text_tutor import TextTutor
from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.app import deps
from engram.app.main import app
from engram.core.models import Completion
from engram.core.service import EngramService
from tests.fakes import FakeLLM

_EXTRACTION = {
    "items": [
        {
            "type": "concept",
            "label": "derivatives",
            "summary": "rate of change",
            "observation": 0.5,
            "evidence": [{"kind": "struggle", "content": "chain rule", "importance": 0.7}],
        }
    ]
}


def _responder(role, messages, schema):
    if role == "extractor":
        return Completion(json=_EXTRACTION, model="fake", usage={"total_tokens": 3})
    return Completion(text="pong", usage={"role": role}, model=f"fake-{role}")


@pytest.fixture
def ctx(monkeypatch):
    storage = InMemoryStorage()
    llm = FakeLLM(responder=_responder, embedder=HashingEmbedder(1024))
    service = EngramService(storage, llm, embed_dim=1024)
    tutor = TextTutor(service)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(deps, "init_singletons", _noop)
    monkeypatch.setattr(deps, "shutdown_singletons", _noop)
    app.dependency_overrides[deps.get_storage] = lambda: storage
    app.dependency_overrides[deps.get_service] = lambda: service
    app.dependency_overrides[deps.get_tutor] = lambda: tutor
    app.dependency_overrides[deps.get_llm] = lambda: llm
    try:
        yield storage, llm
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client(ctx):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "ok"}


async def test_health_degraded(ctx, client):
    storage, _ = ctx
    storage.healthy = False
    r = await client.get("/health")
    assert r.status_code == 503 and r.json()["db"] == "down"


async def test_llm_ping(client):
    r = await client.post("/llm-ping", json={"prompt": "ping"})
    body = r.json()
    assert r.status_code == 200
    assert body["completion"] == "pong" and body["embedding_dim"] == 1024


async def test_ingest_consolidate_graph_recall_evidence_audit(client):
    r = await client.post(
        "/ingest",
        json={
            "learner_id": "alice",
            "events": [
                {"type": "utterance", "text": "what's a derivative?"},
                {"type": "utterance", "text": "the chain rule confuses me"},
            ],
        },
    )
    assert r.status_code == 200 and len(r.json()["ids"]) == 2

    r = await client.post("/consolidate", json={"learner_id": "alice"})
    assert r.json()["stats"]["nodes_created"] == 1

    r = await client.get("/graph", params={"learner_id": "alice"})
    nodes = r.json()["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["label"] == "derivatives" and nodes[0]["evidence_count"] == 1

    r = await client.get("/evidence", params={"node_id": nodes[0]["id"]})
    ev = r.json()["evidence"]
    assert len(ev) == 1 and ev[0]["kind"] == "struggle" and "chain rule" in ev[0]["content"]

    r = await client.post("/recall", json={"learner_id": "alice", "query": "derivatives help"})
    assert "derivatives" in r.json()["text_block"]

    r = await client.get("/audit", params={"learner_id": "alice"})
    ops = {e["op"] for e in r.json()["entries"]}
    assert {"extract", "consolidate"} <= ops


async def test_tutor_turn_endpoint(client):
    r = await client.post("/tutor/turn", json={"learner_id": "bob", "message": "explain limits"})
    body = r.json()
    assert body["reply"] == "pong"
    assert body["events_emitted"] == 2 and "text_block" in body["recall"]


async def test_consolidate_sweep_endpoint(client):
    await client.post(
        "/ingest", json={"learner_id": "carol", "events": [{"type": "utterance", "text": "x"}]}
    )
    r = await client.post("/consolidate-sweep", json={"quiet_seconds": 0})
    assert "carol" in r.json()["learners"]
