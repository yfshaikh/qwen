import httpx
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _client(storage):
    eng = Engram(storage=storage, llm=FakeLLM(), embedder=FakeEmbedder())
    app.dependency_overrides[get_engram] = lambda: eng
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_summary_endpoint():
    s = FakeStorage()
    s.nodes["a"] = Node(id="a", learner_id="L", type=NodeType.CONCEPT, label="a", mastery=0.4)
    try:
        async with _client(s) as c:
            r = await c.get("/insights/summary", params={"learner_id": "L"})
        assert r.status_code == 200
        assert r.json()["concepts"] == 1
    finally:
        app.dependency_overrides.clear()


async def test_review_queue_endpoint_empty_learner():
    try:
        async with _client(FakeStorage()) as c:
            r = await c.get("/insights/review-queue", params={"learner_id": "L"})
        assert r.status_code == 200 and r.json()["items"] == []
    finally:
        app.dependency_overrides.clear()


# Smoke-test the remaining four endpoints over the real ASGI transport so a
# response-model field-name typo (which wouldn't show up in the pure-function
# unit tests) surfaces as a 500 here. Empty learner → 200 + well-formed shape.
async def test_all_insights_endpoints_serialize_for_empty_learner():
    cases = [
        ("/insights/mastery-timeline", "series"),
        ("/insights/hotspots", "hotspots"),
        ("/insights/activity", "days"),
        ("/insights/blockers", "blockers"),
    ]
    try:
        async with _client(FakeStorage()) as c:
            for path, key in cases:
                r = await c.get(path, params={"learner_id": "L"})
                assert r.status_code == 200, f"{path} -> {r.status_code}"
                assert key in r.json(), f"{path} missing {key!r}"
    finally:
        app.dependency_overrides.clear()
