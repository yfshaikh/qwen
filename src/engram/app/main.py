"""Engram FastAPI app. Exposes the memory core over HTTP (see docs/API.md).

Composition lives in deps.py; this module wires endpoints + the lifespan (and an
optional background Keeper sweep loop). CORS is open so the Vite frontend can
call it in dev.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from engram.app import deps
from engram.core.models import LearningEvent, Message

log = logging.getLogger("engram")


async def _sweep_loop(interval: int, quiet: int) -> None:
    """Periodically consolidate learners with quiet pending events (cron backstop)."""
    while True:
        await asyncio.sleep(interval)
        try:
            await deps.get_service().consolidate_sweep(quiet_seconds=quiet)
        except Exception:  # noqa: BLE001 — a sweep failure must not kill the loop.
            log.exception("consolidate sweep failed")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await deps.init_singletons()
    settings = deps.get_settings()
    sweep: asyncio.Task | None = None
    if settings.sweep_enabled:
        sweep = asyncio.create_task(
            _sweep_loop(settings.sweep_interval_seconds, settings.sweep_quiet_seconds)
        )
    try:
        yield
    finally:
        if sweep is not None:
            sweep.cancel()
        await deps.shutdown_singletons()


app = FastAPI(title="Engram", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- request models ---------------------------------------------------- #
class EventIn(BaseModel):
    type: str
    text: str | None = None
    refs: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)


class IngestIn(BaseModel):
    learner_id: str
    events: list[EventIn]


class RecallIn(BaseModel):
    learner_id: str
    query: str
    budget: int = 600


class ConsolidateIn(BaseModel):
    learner_id: str


class SweepIn(BaseModel):
    quiet_seconds: int = 0


class TutorIn(BaseModel):
    learner_id: str
    message: str
    session_id: str | None = None
    doc_ref: dict[str, Any] = Field(default_factory=dict)


class PingIn(BaseModel):
    prompt: str


# --- endpoints --------------------------------------------------------- #
@app.get("/health")
async def health(storage: Any = Depends(deps.get_storage)) -> Any:
    ok = await storage.health()
    if not ok:
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "down"})
    return {"status": "ok", "db": "ok"}


@app.post("/llm-ping")
async def llm_ping(body: PingIn, llm: Any = Depends(deps.get_llm)) -> dict[str, Any]:
    completion = await llm.complete("tutor", [Message(role="user", content=body.prompt)])
    vectors = await llm.embed([body.prompt])
    return {
        "completion": completion.text,
        "embedding_dim": len(vectors[0]) if vectors else 0,
        "usage": completion.usage,
        "model": completion.model,
    }


@app.post("/ingest")
async def ingest(body: IngestIn, service: Any = Depends(deps.get_service)) -> dict[str, Any]:
    events = [
        LearningEvent(
            learner_id=body.learner_id,
            type=e.type,
            text=e.text,
            refs=e.refs,
            signals=e.signals,
        )
        for e in body.events
    ]
    ids = await service.ingest(events)
    return {"ids": ids}


@app.post("/recall")
async def recall(body: RecallIn, service: Any = Depends(deps.get_service)) -> dict[str, Any]:
    result = await service.recall(body.learner_id, body.query, body.budget)
    return {"text_block": result.text_block, "subgraph": result.subgraph}


@app.post("/consolidate")
async def consolidate(
    body: ConsolidateIn, service: Any = Depends(deps.get_service)
) -> dict[str, Any]:
    stats = await service.consolidate(body.learner_id)
    return {"stats": stats}


@app.post("/consolidate-sweep")
async def consolidate_sweep(
    body: SweepIn, service: Any = Depends(deps.get_service)
) -> dict[str, Any]:
    return await service.consolidate_sweep(body.quiet_seconds)


@app.get("/graph")
async def graph(
    learner_id: str,
    focus: str | None = None,
    hops: int = 1,
    service: Any = Depends(deps.get_service),
) -> dict[str, Any]:
    view = await service.graph(learner_id, focus=focus, hops=hops)
    return {"nodes": view.nodes, "edges": view.edges}


@app.get("/evidence")
async def evidence(
    node_id: str, limit: int = 20, service: Any = Depends(deps.get_service)
) -> dict[str, Any]:
    rows = await service.evidence(node_id, limit)
    return {
        "evidence": [
            {
                "id": ev.id,
                "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                "content": ev.content,
                "importance": ev.importance,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in rows
        ]
    }


@app.get("/audit")
async def audit(
    learner_id: str, limit: int = 100, service: Any = Depends(deps.get_service)
) -> dict[str, Any]:
    entries = await service.audit(learner_id, limit)
    return {
        "entries": [
            {
                "op": a.op,
                "rationale": a.rationale,
                "model": a.model,
                "tokens": a.tokens,
                "input_refs": a.input_refs,
                "output_refs": a.output_refs,
                "ts": a.ts.isoformat() if a.ts else None,
            }
            for a in entries
        ]
    }


@app.post("/tutor/turn")
async def tutor_turn(body: TutorIn, tutor: Any = Depends(deps.get_tutor)) -> dict[str, Any]:
    return await tutor.turn(
        body.learner_id,
        body.message,
        session_id=body.session_id,
        doc_ref=body.doc_ref,
    )
