"""The Engram HTTP service — thin FastAPI wrapper over the Engram facade."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from engram.app import deps
from engram.app.deps import get_engram
from engram.app.schemas import (
    AddRequest,
    AddResponse,
    AuditResponse,
    AuditRow,
    ChatMessage,
    ChatRequest,
    ConsolidateRequest,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HealthResponse,
    HistoryResponse,
    RecallRequest,
    RecallResponse,
    ReportOut,
)
from engram.core.models import LearningEvent
from engram.tutor.tutor import Tutor

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
