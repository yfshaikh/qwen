import base64
import json

import httpx

from engram.voice.stt import transcribe


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict, status: int = 200):
        self.payload, self.status, self.seen = payload, status, {}

    async def handle_async_request(self, request):
        self.seen["url"] = str(request.url)
        self.seen["auth"] = request.headers.get("authorization")
        self.seen["body"] = json.loads(request.content)
        return httpx.Response(self.status, json=self.payload)


def _ok(text):
    return {"choices": [{"message": {"content": text}}]}


async def test_transcribe_returns_text(monkeypatch):
    t = _MockTransport(_ok("hello there"))
    monkeypatch.setattr("engram.voice.stt._transport", lambda: t)
    out = await transcribe(b"AUDIO", "audio/webm", api_key="K", model="qwen3-asr-flash")
    assert out == "hello there"
    assert "compatible-mode/v1/chat/completions" in t.seen["url"]
    assert t.seen["auth"] == "Bearer K"
    assert t.seen["body"]["model"] == "qwen3-asr-flash"
    part = t.seen["body"]["messages"][0]["content"][0]
    assert part["type"] == "input_audio"
    expected = f"data:audio/webm;base64,{base64.b64encode(b'AUDIO').decode()}"
    assert part["input_audio"]["data"] == expected
    assert "asr_options" not in t.seen["body"]  # no language -> provider default


async def test_transcribe_passes_language(monkeypatch):
    t = _MockTransport(_ok("hola"))
    monkeypatch.setattr("engram.voice.stt._transport", lambda: t)
    await transcribe(b"A", "audio/webm", api_key="K", model="qwen3-asr-flash",
                     language="es")
    assert t.seen["body"]["asr_options"] == {"language": "es"}


async def test_transcribe_empty_on_silence(monkeypatch):
    t = _MockTransport(_ok(""))
    monkeypatch.setattr("engram.voice.stt._transport", lambda: t)
    assert await transcribe(b"", "audio/webm", api_key="K", model="qwen3-asr-flash") == ""
