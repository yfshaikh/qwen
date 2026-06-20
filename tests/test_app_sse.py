"""SSE /events/stream test.

We exercise the route function and its StreamingResponse generator directly
instead of through httpx's ASGITransport. That transport (0.28.x) buffers the
whole response and only returns once the ASGI app finishes — an intentionally
infinite SSE generator never finishes, so a streaming client hangs forever.
Driving the generator directly tests the real streaming logic and the
disconnect exit without standing up a live server. The production generator is
correct under a real ASGI server (uvicorn), where request.is_disconnected()
fires when the client goes away.
"""

import pytest

from engram.app.main import events_stream
from engram.core.consolidation import AuditEntry, ConsolidationPlan
from engram.core.engram import Engram
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


class _FakeRequest:
    def __init__(self, disconnected: bool = False) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


def _engram() -> Engram:
    return Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder())


async def test_stream_emits_seeded_audit_rows():
    eng = _engram()
    await eng.storage.apply_consolidation(
        ConsolidationPlan(learner_id="a", audit=[AuditEntry(op="extract"), AuditEntry(op="link")])
    )
    resp = await events_stream(_FakeRequest(), learner_id="a", eng=eng)
    assert resp.media_type == "text/event-stream"

    it = resp.body_iterator
    f1 = await anext(it)
    f2 = await anext(it)
    await it.aclose()
    assert "extract" in f1
    assert "link" in f2


async def test_stream_exits_on_disconnect():
    eng = _engram()
    await eng.storage.apply_consolidation(
        ConsolidationPlan(learner_id="a", audit=[AuditEntry(op="extract")])
    )
    resp = await events_stream(_FakeRequest(disconnected=True), learner_id="a", eng=eng)
    with pytest.raises(StopAsyncIteration):
        await anext(resp.body_iterator)
