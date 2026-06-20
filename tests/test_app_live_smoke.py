"""Opt-in: full HTTP path against the live Docker DB (FakeLLM, no API keys).
Skipped unless ENGRAM_LIVE_DB=1."""

import json
import os
import uuid

import httpx
import pytest
from httpx import ASGITransport

pytestmark = pytest.mark.skipif(
    os.environ.get("ENGRAM_LIVE_DB") != "1",
    reason="set ENGRAM_LIVE_DB=1 (Docker DB up) to run the live HTTP smoke",
)

EXTRACTION = json.dumps(
    {"concepts": [{"label": "Limits", "summary": "approach",
                   "evidence": [{"kind": "quiz_correct", "content": "ok"}]}],
     "preferences": [], "goals": [], "relations": []}
)


async def test_full_http_path_live():
    from engram.adapters.storage.postgres import PostgresStorage
    from engram.app.deps import get_engram
    from engram.app.main import app
    from engram.core.engram import Engram
    from tests.fakes import FakeEmbedder, FakeLLM

    learner = f"t-{uuid.uuid4()}"
    storage = PostgresStorage("postgresql://engram:engram@localhost:5432/engram")
    await storage.connect()
    e = Engram(storage=storage, llm=FakeLLM(canned_text=EXTRACTION),
               embedder=FakeEmbedder(dim=1024))
    app.dependency_overrides[get_engram] = lambda: e
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post("/add", json={"events": [
                {"learner_id": learner, "type": "utterance", "text": "limit?"}]})
            rep = await c.post("/consolidate", json={"learner_id": learner})
            assert rep.json()["nodes_created"] == 1
            aud = await c.get("/audit", params={"learner_id": learner})
            assert any(r["op"] == "consolidate" for r in aud.json()["rows"])
            rec = await c.post("/recall", json={"learner_id": learner, "query": "limits"})
            assert "Limits" in rec.json()["text_block"]
    finally:
        app.dependency_overrides.clear()
        await storage.close()
