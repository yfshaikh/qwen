import httpx
import pytest
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text="A limit is the value..."),
               embedder=FakeEmbedder(dim=1024))
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_chat_streams_typed_frames(eng):
    async with _client() as c:
        r = await c.post("/chat", json={"learner_id": "a",
                                        "messages": [{"role": "user", "content": "limits?"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    for marker in ("event: context", "event: delta", "event: saved", "event: done"):
        assert marker in r.text
    assert eng.storage.events[-1].type == "tutor_explanation"  # events were written


async def test_chat_rejects_non_user_last_turn(eng):
    async with _client() as c:
        r = await c.post("/chat", json={"learner_id": "a",
                                        "messages": [{"role": "assistant", "content": "hi"}]})
    assert r.status_code == 400


async def test_chat_validation_rejects_missing_learner_id(eng):
    async with _client() as c:
        r = await c.post("/chat", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 422
