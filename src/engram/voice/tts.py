"""Deepgram Aura streaming TTS over httpx. Port of Marfini api/voice_tutor/tts.py.
Splits over Deepgram's 2000-char cap and speaks every piece (no silent truncation)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

_SPEAK_URL = "https://api.deepgram.com/v1/speak"


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
    text: str, *, api_key: str, model: str
) -> AsyncIterator[bytes]:
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    params = {"model": model, "encoding": "mp3"}
    async with httpx.AsyncClient(transport=_transport(), timeout=30.0) as c:
        for piece in split_for_tts(text):
            async with c.stream(
                "POST", _SPEAK_URL, params=params, headers=headers, json={"text": piece}
            ) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes():
                    if chunk:
                        yield chunk
