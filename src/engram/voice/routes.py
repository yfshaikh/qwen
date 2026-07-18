"""Voice-session HTTP + WebSocket routes. Same handlers, same paths as
formerly in `app/main.py` — just a feature-owned home.

`_consolidating` is the per-learner "consolidating" refcount backing the live
status badge (`/memory/status`, still in `app/main.py`) — it lives here since
the voice WS is what drives it, and is exposed via `is_consolidating()`.
In-process:
# ponytail: single-node only; move to Tair/Redis if we scale out.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from engram.app.deps import get_engram
from engram.core.models import LearningEvent
from engram.voice.pipeline import VoicePipeline
from engram.voice.schemas import SessionsResponse, TurnsResponse, VoiceSessionOut, VoiceTurnOut
from engram.voice.stt import transcribe as stt_transcribe
from engram.voice.tts import stream_speech as tts_stream_speech

voice_router = APIRouter()

_consolidating: dict[str, int] = {}


def _mark_consolidating(learner_id: str) -> None:
    _consolidating[learner_id] = _consolidating.get(learner_id, 0) + 1


def _unmark_consolidating(learner_id: str) -> None:
    n = _consolidating.get(learner_id, 0) - 1
    if n > 0:
        _consolidating[learner_id] = n
    else:
        _consolidating.pop(learner_id, None)


def is_consolidating(learner_id: str) -> bool:
    return _consolidating.get(learner_id, 0) > 0


@voice_router.get("/sessions", response_model=SessionsResponse)
async def sessions(learner_id: str, eng=Depends(get_engram)):
    rows = await eng.list_voice_sessions(learner_id)
    return SessionsResponse(sessions=[VoiceSessionOut(**r) for r in rows])


@voice_router.get("/sessions/{session_id}/turns", response_model=TurnsResponse)
async def session_turns(session_id: str, eng=Depends(get_engram)):
    rows = await eng.list_voice_turns(session_id)
    return TurnsResponse(turns=[VoiceTurnOut(**r) for r in rows])


@voice_router.websocket("/voice")
async def voice(ws: WebSocket, learner_id: str, eng=Depends(get_engram)):
    # NB: inject via Depends (not a direct get_engram() call) so tests'
    # app.dependency_overrides[get_engram] takes effect on the WS route too.
    s = eng.settings
    if not s or not getattr(s, "deepgram_api_key", None):
        await ws.close(code=1011)
        return
    await ws.accept()
    pipeline = VoicePipeline(
        eng, api_key=s.deepgram_api_key, stt_model=s.deepgram_stt_model,
        tts_model=s.deepgram_tts_model, language=s.deepgram_language,
        transcribe=stt_transcribe, stream_speech=tts_stream_speech,
    )
    session_id = await eng.create_voice_session(learner_id)
    await ws.send_json({"type": "session_started", "session_id": session_id})

    async def send_text(msg: dict) -> None:
        await ws.send_json(msg)

    async def send_bytes(b: bytes) -> None:
        await ws.send_bytes(b)

    history: list[dict] = []
    buffer = bytearray()
    mime = "audio/webm"
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                buffer.extend(msg["bytes"])
                continue
            if msg.get("text") is None:
                continue
            data = json.loads(msg["text"])
            kind = data.get("type")
            if kind == "start":
                buffer.clear()
                mime = data.get("mime_type", "audio/webm")
            elif kind == "end":
                audio = bytes(buffer)
                buffer.clear()
                user_text, reply = await pipeline.run_turn(
                    audio, mime, learner_id, history, send_text, send_bytes)
                if user_text:
                    await eng.append_voice_turn(session_id, learner_id, "user", user_text)
                    history.append({"role": "user", "content": user_text})
                if reply:
                    await eng.append_voice_turn(session_id, learner_id, "assistant", reply)
                    history.append({"role": "assistant", "content": reply})
                    await eng.ingest([
                        LearningEvent(learner_id=learner_id, type="utterance", text=user_text),
                        LearningEvent(learner_id=learner_id, type="tutor_explanation", text=reply),
                    ])
            elif kind == "goodbye":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await eng.end_voice_session(session_id)
        _mark_consolidating(learner_id)
        try:
            await eng.consolidate(learner_id)
        except Exception:  # best-effort: consolidation must never break teardown
            pass
        finally:
            _unmark_consolidating(learner_id)
