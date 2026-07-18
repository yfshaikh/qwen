import json

import httpx
import pytest
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage

EXTRACTION = json.dumps(
    {"concepts": [{"label": "Limits", "summary": "s",
                   "evidence": [{"kind": "quiz_correct", "content": "ok"}]}],
     "preferences": [], "goals": [], "relations": []}
)


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text=EXTRACTION),
               embedder=FakeEmbedder(dim=1024))
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_ok(eng):
    async with _client() as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True}


async def test_add_ingests_and_rejects_malformed(eng):
    async with _client() as c:
        ok = await c.post("/add", json={"events": [
            {"learner_id": "a", "type": "utterance", "text": "hi"}]})
        assert ok.status_code == 200 and ok.json() == {"ingested": 1}

        bad = await c.post("/add", json={"events": [{"learner_id": "", "type": "utterance"}]})
        assert bad.status_code == 400
    assert len(eng.storage.events) == 1  # the malformed batch wrote nothing


async def test_recall_returns_block(eng):
    await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Limits",
             salience=0.9, embedding=[1.0] * 1024)
    )
    async with _client() as c:
        r = await c.post("/recall", json={"learner_id": "a", "query": "limits", "budget": 800})
    assert r.status_code == 200
    assert "Limits" in r.json()["text_block"]


async def test_consolidate_then_audit(eng):
    async with _client() as c:
        await c.post("/add", json={"events": [{"learner_id": "a", "type": "utterance", "text": "t"}]})
        rep = await c.post("/consolidate", json={"learner_id": "a"})
        assert rep.status_code == 200
        assert rep.json()["nodes_created"] == 1

        aud = await c.get("/audit", params={"learner_id": "a"})
        assert aud.status_code == 200
        ops = [row["op"] for row in aud.json()["rows"]]
        assert "consolidate" in ops
        assert aud.json()["cursor"] is not None


async def test_recall_validation_rejects_missing_fields(eng):
    async with _client() as c:
        r = await c.post("/recall", json={"query": "x"})  # missing learner_id
    assert r.status_code == 422
