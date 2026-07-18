import httpx
import pytest
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from engram.core.models import LearningEvent
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder())
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_history_maps_events_to_chat_roles(eng):
    await eng.ingest(
        [
            LearningEvent(learner_id="a", type="utterance", text="what is a limit?"),
            LearningEvent(learner_id="a", type="tutor_explanation", text="A limit is…"),
            LearningEvent(learner_id="a", type="note", text="not a message"),
            LearningEvent(learner_id="b", type="utterance", text="other learner"),
        ]
    )
    async with _client() as c:
        r = await c.get("/history", params={"learner_id": "a"})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "what is a limit?"),
        ("assistant", "A limit is…"),
    ]  # 'note' skipped (not a chat turn), learner 'b' excluded


async def test_history_requires_learner_id(eng):
    async with _client() as c:
        r = await c.get("/history")
    assert r.status_code == 422
