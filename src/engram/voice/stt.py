"""Qwen ASR batch STT (qwen3-asr-flash) over DashScope's OpenAI-compatible
REST endpoint via httpx. Audio goes up as a base64 data URI in an
`input_audio` message part; the transcript comes back as the completion text.
Key/model are passed in by the caller — no env access here."""

from __future__ import annotations

import asyncio
import base64

import httpx

_CHAT_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"


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
    data_uri = f"data:{mime_type};base64,{base64.b64encode(audio).decode()}"
    body: dict = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [{"type": "input_audio", "input_audio": {"data": data_uri}}],
        }],
    }
    if language:
        # Raw-HTTP equivalent of the SDK's extra_body: top-level key.
        body["asr_options"] = {"language": language}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last: Exception | None = None
    for attempt in range(3):  # ponytail: 3x manual retry, no tenacity dep
        try:
            async with httpx.AsyncClient(transport=_transport(), timeout=60.0) as c:
                r = await c.post(_CHAT_URL, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
            choices = data.get("choices") or []
            if not choices:
                return ""
            return (choices[0]["message"].get("content") or "").strip()
        except Exception as e:  # noqa: BLE001 — retry any transport/parse error
            last = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Qwen ASR failed after 3 attempts: {last}")
