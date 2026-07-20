import json

import httpx

from engram.voice.tts import split_for_tts, stream_speech


def test_split_never_drops_text():
    text = "a. " * 1000  # 3000 chars
    pieces = split_for_tts(text, limit=2000)
    assert all(len(p) <= 2000 for p in pieces)
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")
    assert len(pieces) >= 2


def test_split_short_text_one_piece():
    assert split_for_tts("hello") == ["hello"]


class _MockTransport(httpx.AsyncBaseTransport):
    """POST -> synth response with an audio URL; GET on that URL -> WAV bytes."""

    def __init__(self):
        self.synth_calls = 0
        self.seen_body = None

    async def handle_async_request(self, request):
        if request.method == "POST":
            self.synth_calls += 1
            self.seen_body = json.loads(request.content)
            return httpx.Response(
                200, json={"output": {"audio": {"url": "https://oss.example/a.wav"}}})
        return httpx.Response(200, content=b"WAV")


async def test_stream_speech_yields_chunks_per_piece(monkeypatch):
    t = _MockTransport()
    monkeypatch.setattr("engram.voice.tts._transport", lambda: t)
    text = "x" * 2500  # forces 2 pieces
    chunks = [c async for c in stream_speech(text, api_key="K", model="qwen3-tts-flash")]
    assert b"".join(chunks) == b"WAVWAV"
    assert t.synth_calls == 2  # both pieces spoken, none dropped
    assert t.seen_body["model"] == "qwen3-tts-flash"
    assert t.seen_body["input"]["voice"] == "Cherry"  # default voice


async def test_stream_speech_passes_voice(monkeypatch):
    t = _MockTransport()
    monkeypatch.setattr("engram.voice.tts._transport", lambda: t)
    [c async for c in stream_speech("hi", api_key="K", model="qwen3-tts-flash",
                                    voice="Ethan")]
    assert t.seen_body["input"]["voice"] == "Ethan"
