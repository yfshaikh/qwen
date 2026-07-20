"""Qwen TTS (qwen3-tts-flash) over DashScope's multimodal-generation REST
endpoint via httpx. Each request returns a short-lived URL to a complete WAV
file (24kHz 16-bit mono); we download it and yield it as a SINGLE bytes object
per sentence. That one-message-per-utterance framing is load-bearing: the WS
preserves message boundaries, so the client receives each sentence as one
complete, playable audio file (see web/src/voice/voice.ts).
Splits long text and speaks every piece (no silent truncation)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

_TTS_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def _transport() -> httpx.AsyncBaseTransport | None:
    return None  # real network; tests monkeypatch


def split_for_tts(text: str, limit: int = 2000) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    pieces, cur = [], ""
    for word in text.split(" "):
        # Handle words longer than limit by breaking them at character boundary
        while len(word) > limit:
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(word[:limit])
            word = word[limit:]

        candidate = f"{cur} {word}".strip()
        if len(candidate) > limit and cur:
            pieces.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        pieces.append(cur)
    return pieces


async def stream_speech(
    text: str, *, api_key: str, model: str, voice: str = "Cherry"
) -> AsyncIterator[bytes]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(transport=_transport(), timeout=60.0) as c:
        for piece in split_for_tts(text):
            r = await c.post(_TTS_URL, headers=headers, json={
                "model": model,
                "input": {"text": piece, "voice": voice, "language_type": "Auto"},
            })
            r.raise_for_status()
            url = r.json()["output"]["audio"]["url"]  # valid ~24h; fetch now
            audio = await c.get(url)
            audio.raise_for_status()
            yield audio.content  # one complete WAV = one WS message
