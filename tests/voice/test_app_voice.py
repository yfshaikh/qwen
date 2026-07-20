import json

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport

from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture
def eng():
    e = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text="Limits are core."),
               embedder=FakeEmbedder(dim=1024), settings=_settings())
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _settings():
    # Real Settings so recall()/consolidate() find their recall_*/keeper_* fields.
    # `_env_file=None` ignores any on-disk .env; populate_by_name lets us pass
    # field names directly.
    from engram.app.config import Settings
    return Settings(
        dashscope_api_key="x", database_url="x",
        model_tutor="m", model_extractor="m", model_reflector="m", model_embedder="m",
        _env_file=None,
    )


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_sessions_and_turns_endpoints(eng):
    sid = await eng.storage.create_voice_session("a")
    await eng.storage.append_voice_turn(sid, "a", "user", "hi")
    async with _client() as c:
        s = await c.get("/sessions", params={"learner_id": "a"})
        assert s.status_code == 200 and s.json()["sessions"][0]["id"] == sid
        t = await c.get(f"/sessions/{sid}/turns")
        assert t.status_code == 200 and t.json()["turns"][0]["text"] == "hi"


async def test_memory_status_endpoint(eng):
    async with _client() as c:
        r = await c.get("/memory/status", params={"learner_id": "a"})
    assert r.status_code == 200 and r.json() == {"consolidating": False}


def test_voice_ws_turn(eng, monkeypatch):
    # Stub the DashScope voice adapters so no network is touched.
    async def fake_transcribe(audio, mime, *, api_key, model, language=None):
        return "what are limits"

    async def fake_stream_speech(text, *, api_key, model, voice="Cherry"):
        yield b"MP3"

    monkeypatch.setattr("engram.voice.routes.stt_transcribe", fake_transcribe)
    monkeypatch.setattr("engram.voice.routes.tts_stream_speech", fake_stream_speech)

    client = TestClient(app)
    with client.websocket_connect("/voice?learner_id=a") as ws:
        started = ws.receive_json()
        assert started["type"] == "session_started"
        ws.send_json({"type": "start", "mime_type": "audio/webm"})
        ws.send_bytes(b"AUDIO")
        ws.send_json({"type": "end", "mime_type": "audio/webm"})
        kinds, got_audio = [], False
        while True:
            msg = ws.receive()
            if "text" in msg and msg["text"] is not None:
                data = json.loads(msg["text"])
                kinds.append(data["type"])
                if data["type"] == "turn_done":
                    break
            elif msg.get("bytes"):
                got_audio = True
        assert "transcript" in kinds and "token" in kinds and got_audio
    # user turn + reply persisted
    turns = eng.storage.voice_turns
    assert [t["role"] for t in turns] == ["user", "assistant"]
