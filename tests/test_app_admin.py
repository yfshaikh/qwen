import httpx
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_repair_merges_endpoint():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=8))
    app.dependency_overrides[get_engram] = lambda: eng
    try:
        async with _client() as c:
            r = await c.post("/admin/repair-merges", json={"learner_id": "L"})
            assert r.status_code == 200
            body = r.json()
            assert body["merged"] == 0 and body["skipped"] is False
            missing = await c.post("/admin/repair-merges", json={})
            assert missing.status_code == 422
    finally:
        app.dependency_overrides.clear()
