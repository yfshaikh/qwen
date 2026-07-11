import httpx

from engram.voice.stt import transcribe


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict, status: int = 200):
        self.payload, self.status, self.seen = payload, status, {}

    async def handle_async_request(self, request):
        self.seen["url"] = str(request.url)
        self.seen["auth"] = request.headers.get("authorization")
        self.seen["ctype"] = request.headers.get("content-type")
        self.seen["body"] = request.content
        return httpx.Response(self.status, json=self.payload)


def _ok(text):
    return {"results": {"channels": [{"alternatives": [{"transcript": text}]}]}}


async def test_transcribe_returns_text(monkeypatch):
    t = _MockTransport(_ok("hello there"))
    monkeypatch.setattr("engram.voice.stt._transport", lambda: t)
    out = await transcribe(b"AUDIO", "audio/webm", api_key="K", model="nova-3")
    assert out == "hello there"
    assert "model=nova-3" in t.seen["url"]
    assert t.seen["auth"] == "Token K"
    assert t.seen["ctype"] == "audio/webm"
    assert t.seen["body"] == b"AUDIO"


async def test_transcribe_empty_on_silence(monkeypatch):
    t = _MockTransport(_ok(""))
    monkeypatch.setattr("engram.voice.stt._transport", lambda: t)
    assert await transcribe(b"", "audio/webm", api_key="K", model="nova-3") == ""
