"""Per-turn voice orchestrator: STT -> recall -> LLM (stream) -> TTS (stream).
Host-adapter glue; consumes the Engram facade, never core internals.

Sentence-buffered TTS for low time-to-first-audio. The TTS tail is shielded:
a TTS failure is surfaced as an `error` event but never aborts the turn, so the
caller always gets (user_text, reply) to persist. (Marfini regression lesson.)

Inline whiteboard/pointer tags ([draw:...], [point:src-x], [show:panel-N]) are
stripped from the stream (never spoken or displayed) and turned into WS events:

- a `[draw:...]` tag kicks off an SVG render (GLM via the diagram role) the
  moment it is parsed — concurrently, so narration isn't blocked — emitting
  `whiteboard_pending` immediately and `whiteboard_panel`/`whiteboard_error`
  when the render lands (drained between sentences and at end of turn);
- a `[point:...]`/etc gesture is emitted as a `clicky_gesture` event just before
  its sentence's audio bytes, so the client can sync the pointer to the voice.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from engram.voice.clicky.tags import GestureTagParser
from engram.voice.prompt import compose_voice
from engram.voice import stt as stt_mod
from engram.voice import tts as tts_mod
from engram.whiteboard.generate import Panel, generate_panel

# A sentence terminator (with trailing quotes/brackets/space). Matching to its
# end() gives exact character offsets so a gesture never fires ahead of the
# sentence its tag sat in.
_SENTENCE = re.compile(r'[.!?]+["\')\]]*(?:\s+|$)')

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

        # --- Inline-tag state ---
        parser = GestureTagParser()
        # Gestures wait as (clean_stream_pos, wire_event); a gesture fires only
        # once the text up to its position has been handed to TTS.
        pending_gestures: list[tuple[int, dict]] = []
        clean_produced = 0  # total clean chars appended to buf this turn
        clean_spoken = 0    # total clean chars handed to TTS so far
        # (panel_id, task) for in-flight renders; drained as they finish.
        panel_tasks: list[tuple[str, asyncio.Task[Panel]]] = []

        async def emit_gestures(through: int | None = None) -> None:
            # pending is ascending by position; due ones are a front prefix.
            while pending_gestures and (through is None or pending_gestures[0][0] <= through):
                _pos, ev = pending_gestures.pop(0)
                await send_text({"type": "clicky_gesture",
                                 "gesture_id": uuid.uuid4().hex, **ev})

        async def drain_panels(wait: bool = False) -> None:
            for panel_id, task in list(panel_tasks):
                if wait and not task.done():
                    try:
                        await task
                    except Exception:  # noqa: BLE001 — reported below
                        pass
                if task.done():
                    panel_tasks.remove((panel_id, task))
                    try:
                        panel = task.result()
                    except Exception as e:  # noqa: BLE001 — render failure -> WS error
                        await send_text({"type": "whiteboard_error",
                                         "panel_id": panel_id, "message": str(e)})
                        continue
                    await send_text({
                        "type": "whiteboard_panel", "panel_id": panel_id,
                        "html": panel.html, "caption": panel.caption,
                        "intent": panel.intent, "anchors": panel.anchors,
                        "model": panel.model,
                    })

        async def start_draw(ev: dict) -> None:
            panel_id = uuid.uuid4().hex
            await send_text({"type": "whiteboard_pending", "panel_id": panel_id,
                             "intent": ev["intent"]})
            task: asyncio.Task[Panel] = asyncio.create_task(
                generate_panel(self.eng.llm, ev["intent"], ev.get("anchors") or None))
            panel_tasks.append((panel_id, task))

        reply, buf = "", ""
        spoken_any = False
        await send_text({"type": "status", "phase": "speaking"})
        async for delta in self.eng.llm.stream("tutor", prompt):
            clean, events = parser.feed(delta)
            for ev in events:
                if ev["kind"] == "draw":
                    await start_draw(ev)  # fire the render ASAP (concurrent)
                else:
                    at = clean_produced + ev.pop("_at", 0)
                    pending_gestures.append((at, {
                        "gesture": ev["gesture"], "anchor": ev["anchor"],
                        **({"note": ev["note"]} if ev.get("note") else {}),
                    }))
            if clean:
                reply += clean
                buf += clean
                clean_produced += len(clean)
                await send_text({"type": "token", "text": clean})
            # Flush every complete sentence eagerly (exact offsets via .end()).
            while True:
                m = _SENTENCE.search(buf)
                if not m:
                    break
                sentence, buf = buf[:m.end()], buf[m.end():]
                clean_spoken += len(sentence)
                # This sentence's (or earlier) gestures ride just ahead of its
                # audio; a later sentence's tag waits. Then emit any finished
                # panel so its iframe mounts before its src-* gestures resolve.
                await emit_gestures(clean_spoken)
                await drain_panels()
                spoken_any = await self._speak(sentence, send_bytes, send_text) or spoken_any

        leftover = parser.flush()
        if leftover:
            reply += leftover
            buf += leftover
            await send_text({"type": "token", "text": leftover})
        if buf.strip():
            clean_spoken += len(buf)
            await emit_gestures(clean_spoken)
            spoken_any = await self._speak(buf, send_bytes, send_text) or spoken_any
        # Release any remaining gestures and await any still-rendering panels so
        # they land before the turn closes.
        await emit_gestures()
        await drain_panels(wait=True)

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
