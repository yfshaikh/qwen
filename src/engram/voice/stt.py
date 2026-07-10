"""Deepgram batch STT over httpx REST. Port of Marfini api/voice_tutor/stt.py,
decoupled from Marfini env access — key/model are passed in by the caller."""

from __future__ import annotations

import asyncio

import httpx

_LISTEN_URL = "https://api.deepgram.com/v1/listen"


def _transport() -> httpx.AsyncBaseTransport | None:
    return None  # real network; tests monkeypatch this to inject a mock


async def transcribe(
    audio: bytes,
    mime_type: str,
    *,
    api_key: str,
    model: str,
    language: str | None = None,
) -> str:
    if not audio:
        return ""
    params = {"model": model, "smart_format": "true"}
    if language:
        params["language"] = language
    headers = {"Authorization": f"Token {api_key}", "Content-Type": mime_type}
    last: Exception | None = None
    for attempt in range(3):  # ponytail: 3x manual retry, no tenacity dep
        try:
            async with httpx.AsyncClient(transport=_transport(), timeout=30.0) as c:
                r = await c.post(_LISTEN_URL, params=params, headers=headers, content=audio)
                r.raise_for_status()
                data = r.json()
            alts = data["results"]["channels"][0]["alternatives"]
            return alts[0]["transcript"].strip() if alts else ""
        except Exception as e:  # noqa: BLE001 — retry any transport/parse error
            last = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Deepgram STT failed after 3 attempts: {last}")
