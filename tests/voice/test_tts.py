import httpx
import pytest

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
    def __init__(self):
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        return httpx.Response(200, content=b"MP3")


async def test_stream_speech_yields_chunks_per_piece(monkeypatch):
    t = _MockTransport()
    monkeypatch.setattr("engram.voice.tts._transport", lambda: t)
    text = "x" * 2500  # forces 2 pieces
    chunks = [c async for c in stream_speech(text, api_key="K", model="aura-2-thalia-en")]
    assert b"".join(chunks) == b"MP3MP3"
    assert t.calls == 2  # both pieces spoken, none dropped
