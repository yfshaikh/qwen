"""The Engram HTTP service — thin FastAPI wrapper over the Engram facade."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from engram.app import deps
from engram.app.deps import get_engram
from engram.app.schemas import (
    ActivityDay,
    ActivityResponse,
    AddRequest,
    AddResponse,
    AuditResponse,
    AuditRow,
    Blocker,
    BlockersResponse,
    ChatMessage,
    ChatRequest,
    ConsolidateRequest,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HealthResponse,
    HistoryResponse,
    Hotspot,
    HotspotsResponse,
    InsightsSummary,
    MasteryTimelineResponse,
    MemoryStatusResponse,
    RecallRequest,
    RecallResponse,
    ReportOut,
    ReviewItem,
    ReviewQueueResponse,
    SessionsResponse,
    TurnsResponse,
    VoiceSessionOut,
    VoiceTurnOut,
)
from engram.core.models import LearningEvent
from engram.eval import runs as eval_runs
from engram.eval.clock import SimClock
from engram.eval.runner import execute_run
from engram.eval.scenario import load_scenario
from engram.insights import Insights
from engram.tutor.tutor import Tutor
from engram.voice.pipeline import VoicePipeline
from engram.voice.stt import transcribe as stt_transcribe
from engram.voice.tts import stream_speech as tts_stream_speech

DEFAULT_POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    await deps.init_engram()
    try:
        yield
    finally:
        await deps.shutdown_engram()


app = FastAPI(title="Engram", lifespan=lifespan)

# Per-learner "consolidating" refcount for the live status badge. In-process:
# ponytail: single-node only; move to Tair/Redis if we scale out.
_consolidating: dict[str, int] = {}


def _mark_consolidating(learner_id: str) -> None:
    _consolidating[learner_id] = _consolidating.get(learner_id, 0) + 1


def _unmark_consolidating(learner_id: str) -> None:
    n = _consolidating.get(learner_id, 0) - 1
    if n > 0:
        _consolidating[learner_id] = n
    else:
        _consolidating.pop(learner_id, None)


@app.get("/health", response_model=HealthResponse)
async def health(eng=Depends(get_engram)):
    db = await eng.health()
    return HealthResponse(status="ok" if db else "degraded", db=db)


@app.post("/add", response_model=AddResponse)
async def add(req: AddRequest, eng=Depends(get_engram)):
    events = [
        LearningEvent(learner_id=e.learner_id, type=e.type, text=e.text,
                      refs=e.refs, signals=e.signals)
        for e in req.events
    ]
    try:
        await eng.ingest(events)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AddResponse(ingested=len(events))


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest, eng=Depends(get_engram)):
    res = await eng.recall(req.learner_id, req.query, req.budget)
    return RecallResponse(text_block=res.text_block, subgraph=res.subgraph)


@app.post("/consolidate", response_model=ReportOut)
async def consolidate(req: ConsolidateRequest, eng=Depends(get_engram)):
    r = await eng.consolidate(req.learner_id)
    return ReportOut(
        learner_id=r.learner_id, processed_events=r.processed_events,
        nodes_created=r.nodes_created, nodes_updated=r.nodes_updated,
        edges_created=r.edges_created, merged=r.merged, forgotten=r.forgotten,
        errors=r.errors, skipped=r.skipped,
    )


@app.get("/audit", response_model=AuditResponse)
async def audit(learner_id: str, since: datetime | None = None, limit: int = 100,
                eng=Depends(get_engram)):
    rows = await eng.audit(learner_id, since, limit)
    cursor = rows[-1]["ts"] if rows else None
    return AuditResponse(rows=[AuditRow(**r) for r in rows], cursor=cursor)


def _sse_frame(row: dict) -> str:
    out = dict(row)
    if isinstance(out.get("ts"), datetime):
        out["ts"] = out["ts"].isoformat()
    return f"data: {json.dumps(out)}\n\n"


@app.get("/events/stream")
async def events_stream(request: Request, learner_id: str,
                        since: datetime | None = None, eng=Depends(get_engram)):
    async def gen():
        cursor = since
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            rows = await eng.audit(learner_id, cursor, 100)
            if rows:
                for r in rows:
                    yield _sse_frame(r)
                cursor = rows[-1]["ts"]
                idle = 0.0
            else:
                idle += DEFAULT_POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    idle = 0.0
            await asyncio.sleep(DEFAULT_POLL_SECONDS)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/graph", response_model=GraphResponse)
async def graph(learner_id: str, focus: str | None = None, eng=Depends(get_engram)):
    gv = await eng.graph(learner_id, focus)
    return GraphResponse(
        nodes=[GraphNode(**n) for n in gv.nodes],
        edges=[GraphEdge(**e) for e in gv.edges],
    )


# --- insights (read-only analytics) ---------------------------------------
# NB: auth-less like every route here (accepted demo posture).
@app.get("/insights/summary", response_model=InsightsSummary)
async def insights_summary(learner_id: str, eng=Depends(get_engram)):
    return InsightsSummary(**await Insights(eng.storage).summary(learner_id))


@app.get("/insights/mastery-timeline", response_model=MasteryTimelineResponse)
async def insights_timeline(learner_id: str, node_ids: str | None = None,
                            eng=Depends(get_engram)):
    # drop blanks so "a,,b" or a trailing comma can't reach ANY($::uuid[]) as an
    # empty string (asyncpg would reject it -> 500); [] means "no ids" == None.
    ids = [s for s in node_ids.split(",") if s.strip()] if node_ids else None
    series = await Insights(eng.storage).mastery_timeline(learner_id, ids or None)
    return MasteryTimelineResponse(series=series)


@app.get("/insights/hotspots", response_model=HotspotsResponse)
async def insights_hotspots(learner_id: str, k: int = 5, eng=Depends(get_engram)):
    return HotspotsResponse(
        hotspots=[Hotspot(**h) for h in await Insights(eng.storage).hotspots(learner_id, k)])


@app.get("/insights/activity", response_model=ActivityResponse)
async def insights_activity(learner_id: str, days: int = 30, eng=Depends(get_engram)):
    return ActivityResponse(
        days=[ActivityDay(**d) for d in await Insights(eng.storage).activity(learner_id, days)])


@app.get("/insights/review-queue", response_model=ReviewQueueResponse)
async def insights_review_queue(learner_id: str, k: int = 5, eng=Depends(get_engram)):
    return ReviewQueueResponse(
        items=[ReviewItem(**i) for i in await Insights(eng.storage).review_queue(learner_id, k)])


@app.get("/insights/blockers", response_model=BlockersResponse)
async def insights_blockers(learner_id: str, eng=Depends(get_engram)):
    return BlockersResponse(
        blockers=[Blocker(**b) for b in await Insights(eng.storage).blockers(learner_id)])


# utterance/tutor_explanation are the tutor's event types; map them back to chat
# roles so a client can resume a conversation. Other event types are not messages.
_HISTORY_ROLES = {"utterance": "user", "tutor_explanation": "assistant"}


@app.get("/history", response_model=HistoryResponse)
async def history(learner_id: str, limit: int = 200, eng=Depends(get_engram)):
    events = await eng.events(learner_id, limit)
    msgs = [
        ChatMessage(role=_HISTORY_ROLES[e.type], content=e.text)
        for e in events
        if e.type in _HISTORY_ROLES and e.text
    ]
    return HistoryResponse(messages=msgs)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/chat")
async def chat(req: ChatRequest, eng=Depends(get_engram)):
    if req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="messages must end with a user turn")
    tutor = Tutor(eng)
    msgs = [m.model_dump() for m in req.messages]

    async def gen():
        try:
            async for event, data in tutor.turn(req.learner_id, msgs, req.budget):
                yield _sse_event(event, data)
        except Exception as exc:  # failure after 200 already sent → in-band error frame
            yield _sse_event("error", {"detail": str(exc)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/sessions", response_model=SessionsResponse)
async def sessions(learner_id: str, eng=Depends(get_engram)):
    rows = await eng.list_voice_sessions(learner_id)
    return SessionsResponse(sessions=[VoiceSessionOut(**r) for r in rows])


@app.get("/sessions/{session_id}/turns", response_model=TurnsResponse)
async def session_turns(session_id: str, eng=Depends(get_engram)):
    rows = await eng.list_voice_turns(session_id)
    return TurnsResponse(turns=[VoiceTurnOut(**r) for r in rows])


@app.get("/memory/status", response_model=MemoryStatusResponse)
async def memory_status(learner_id: str):
    return MemoryStatusResponse(consolidating=_consolidating.get(learner_id, 0) > 0)


@app.websocket("/voice")
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


@app.post("/admin/repair-merges")
async def admin_repair_merges(body: dict, eng=Depends(get_engram)):
    # NB: auth-less like every route here (accepted demo posture). Do not ship
    # to a shared environment without adding auth.
    learner_id = body.get("learner_id")
    if not learner_id:
        raise HTTPException(status_code=422, detail="learner_id required")
    return await eng.repair_merges(learner_id)


# --- eval harness surface (flag-gated; spec eval-harness-v2) -----------------
_RUNS_BASE = eval_runs.RUNS_DIR
_SCENARIOS_DIR = Path("eval/scenarios")
_eval_tasks: dict[str, "asyncio.Task"] = {}
_DIR_RE = re.compile(r"[A-Za-z0-9._-]+")


def _eval_enabled(eng) -> None:
    if not getattr(eng.settings, "eval_ui", False):
        raise HTTPException(status_code=404)


def _run_dir(name: str) -> Path:
    # Path-traversal guard: the regex allows dots, so bare "."/".." (which
    # resolve to eval/runs itself or its parent) must be rejected explicitly.
    if name in (".", "..") or not _DIR_RE.fullmatch(name):
        raise HTTPException(status_code=404)
    d = _RUNS_BASE / name
    if not (d / "run.json").exists():
        raise HTTPException(status_code=404)
    return d


def _load_scenarios() -> dict[str, tuple[Path, list[str]]]:
    out: dict[str, tuple[Path, list[str]]] = {}
    for p in sorted(_SCENARIOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if data.get("id"):
            names = [c if isinstance(c, str) else c.get("name", "?")
                     for c in data.get("checks", []) or []]
            out[data["id"]] = (p, names)
    return out


@app.get("/eval/scenarios")
async def eval_scenarios(eng=Depends(get_engram)):
    _eval_enabled(eng)
    return {"scenarios": [{"id": sid, "path": str(p), "checks": names}
                          for sid, (p, names) in _load_scenarios().items()]}


@app.get("/eval/runs")
async def eval_runs_list(eng=Depends(get_engram)):
    _eval_enabled(eng)
    rows = eval_runs.list_runs(base_dir=_RUNS_BASE)
    for r in rows:
        t = _eval_tasks.get(r.get("dir", ""))
        r["alive"] = bool(t and not t.done())
    return {"runs": rows}


@app.post("/eval/runs", status_code=202)
async def eval_run_launch(body: dict, eng=Depends(get_engram)):
    _eval_enabled(eng)
    if any(not t.done() for t in _eval_tasks.values()):
        raise HTTPException(status_code=409, detail="a run is already in progress")
    scenarios = _load_scenarios()
    sid = body.get("scenario_id")
    if sid not in scenarios:
        raise HTTPException(status_code=404, detail=f"unknown scenario; known: {sorted(scenarios)}")
    sc = load_scenario(scenarios[sid][0])
    run_id, run_dir = eval_runs.new_run(sc.id, base_dir=_RUNS_BASE)
    checks = body.get("checks")
    budget = body.get("budget_usd")
    task = asyncio.create_task(execute_run(
        eng, sc, run_dir, checks=checks, max_cost_usd=budget, clock=SimClock(),
        emit=lambda e: eval_runs.append_event(run_dir, e)))
    _eval_tasks[run_dir.name] = task
    return {"run_id": run_id, "dir": run_dir.name}


@app.get("/eval/runs/{name}")
async def eval_run_detail(name: str, eng=Depends(get_engram)):
    _eval_enabled(eng)
    return eval_runs.read_run(_run_dir(name))


@app.get("/eval/runs/{name}/snapshots/{n}")
async def eval_run_snapshot(name: str, n: int, eng=Depends(get_engram)):
    _eval_enabled(eng)
    p = _run_dir(name) / "snapshots" / f"session-{n}.json"
    if not p.exists():
        raise HTTPException(status_code=404)
    return json.loads(p.read_text())


@app.post("/eval/runs/{name}/cancel")
async def eval_run_cancel(name: str, eng=Depends(get_engram)):
    _eval_enabled(eng)
    t = _eval_tasks.get(name)
    if t and not t.done():
        t.cancel()
        return {"cancelled": True}
    return {"cancelled": False}


@app.get("/eval/runs/{name}/events")
async def eval_run_events(request: Request, name: str, eng=Depends(get_engram)):
    _eval_enabled(eng)
    run_dir = _run_dir(name)

    async def gen():
        cursor, idle = 0, 0.0
        while True:
            if await request.is_disconnected():
                break
            events, cursor = eval_runs.read_events(run_dir, cursor)
            for e in events:
                yield f"data: {json.dumps(e, default=str)}\n\n"
                idle = 0.0
            t = _eval_tasks.get(name)
            alive = bool(t and not t.done())
            if events and events[-1].get("type") == "status" and not alive \
                    and events[-1].get("status") != "running":
                break  # terminal status replayed; stream complete
            if not events:
                idle += DEFAULT_POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    idle = 0.0
            await asyncio.sleep(DEFAULT_POLL_SECONDS)

    return StreamingResponse(gen(), media_type="text/event-stream")
