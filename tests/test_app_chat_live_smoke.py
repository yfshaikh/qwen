"""Opt-in: a real streamed /chat turn against DashScope + Postgres.
Skipped unless ENGRAM_LIVE_LLM=1 and ENGRAM_LIVE_DB=1 (and .env keys present)."""

import os
import uuid

import httpx
import pytest
from httpx import ASGITransport

pytestmark = pytest.mark.skipif(
    os.environ.get("ENGRAM_LIVE_LLM") != "1" or os.environ.get("ENGRAM_LIVE_DB") != "1",
    reason=(
        "set ENGRAM_LIVE_LLM=1 and ENGRAM_LIVE_DB=1 (keys + Docker DB) "
        "to run the live chat smoke"
    ),
)


async def test_chat_live_streams_real_reply():
    from engram.app.deps import get_engram
    from engram.app.main import app
    from engram.core.engram import Engram

    learner = f"t-{uuid.uuid4()}"
    eng = Engram.from_env()
    await eng.connect()
    app.dependency_overrides[get_engram] = lambda: eng
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                "/chat",
                json={
                    "learner_id": learner,
                    "messages": [{"role": "user", "content": "what is a derivative?"}],
                },
            )
        assert r.status_code == 200
        assert "event: delta" in r.text  # a real reply streamed
        assert "event: saved" in r.text  # events written
        assert "event: done" in r.text
    finally:
        app.dependency_overrides.clear()
        await eng.aclose()
