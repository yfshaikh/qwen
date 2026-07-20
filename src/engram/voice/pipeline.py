"""Per-turn voice orchestrator: STT -> recall -> LLM (stream) -> TTS (stream).
Host-adapter glue; consumes the Engram facade, never core internals.

Sentence-buffered TTS for low time-to-first-audio. The TTS tail is shielded:
a TTS failure is surfaced as an `error` event but never aborts the turn, so the
caller always gets (user_text, reply) to persist. (Marfini regression lesson.)"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from engram.voice.prompt import compose_voice
from engram.voice import stt as stt_mod
from engram.voice import tts as tts_mod

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

SendText = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]


class VoicePipeline:
    def __init__(
        self, eng: Any, *, api_key: str, stt_model: str, tts_model: str,
        tts_voice: str = "Cherry", language: str | None = None,
        transcribe=None, stream_speech=None,
    ) -> None:
        self.eng = eng
        self.api_key = api_key
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.language = language
        # Injectable for tests; default to the real adapters.
        self._transcribe = transcribe or stt_mod.transcribe
        self._stream_speech = stream_speech or tts_mod.stream_speech

    async def run_turn(
        self, audio: bytes, mime_type: str, learner_id: str,
        history: list[dict], send_text: SendText, send_bytes: SendBytes,
    ) -> tuple[str, str]:
        await send_text({"type": "status", "phase": "transcribing"})
        user_text = await self._transcribe(
            audio, mime_type, api_key=self.api_key,
            model=self.stt_model, language=self.language,
        )
        if not user_text:
            await send_text({"type": "status", "phase": "idle"})
            return "", ""
        await send_text({"type": "transcript", "role": "user", "text": user_text})

        await send_text({"type": "status", "phase": "thinking"})
        res = await self.eng.recall(learner_id, user_text)
        prompt = compose_voice(res.text_block, history, user_text)

        reply, buf = "", ""
        spoken_any = False
        await send_text({"type": "status", "phase": "speaking"})
        async for delta in self.eng.llm.stream("tutor", prompt):
            reply += delta
            buf += delta
            await send_text({"type": "token", "text": delta})
            parts = _SENTENCE_END.split(buf)
            if len(parts) > 1:
                for sentence in parts[:-1]:
                    spoken_any = await self._speak(sentence, send_bytes, send_text) or spoken_any
                buf = parts[-1]
        if buf.strip():
            spoken_any = await self._speak(buf, send_bytes, send_text) or spoken_any

        await send_text({"type": "transcript", "role": "assistant", "text": reply})
        await send_text({"type": "usage", "usage": {"reply_tokens": self.eng._token_count(reply)}})
        await send_text({"type": "status", "phase": "idle"})
        await send_text({"type": "turn_done"})
        return user_text, reply

    async def _speak(self, text: str, send_bytes: SendBytes, send_text: SendText) -> bool:
        text = text.strip()
        if not text:
            return False
        try:
            async for chunk in self._stream_speech(
                text, api_key=self.api_key, model=self.tts_model, voice=self.tts_voice
            ):
                await send_bytes(chunk)
            return True
        except Exception as e:  # noqa: BLE001 — TTS tail must never abort the turn
            await send_text({"type": "error", "message": f"tts failed: {e}"})
            return False
