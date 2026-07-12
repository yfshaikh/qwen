"""Auth-injectable FastAPI router exposing Engram's observability surface.

The host owns auth: `learner_id_dep` / `admin_dep` are FastAPI dependencies
returning the caller's learner id. Admin routes are REGISTERED ONLY when
`admin_dep` is provided — there is no unauthenticated-admin failure mode.
Engram failures degrade to `enabled: false` payloads with HTTP 200.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from engram.app.schemas import GraphEdge, GraphNode
from engram.host import EngramHost

logger = logging.getLogger("engram.integrations.fastapi")


class MemGraphResponse(BaseModel):
    enabled: bool = True
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class MemAuditRow(BaseModel):
    id: str
    op: str
    rationale: str | None = None
    model: str | None = None
    tokens: int | None = None
    cost: float | None = None
    ts: datetime | None = None


class MemAuditResponse(BaseModel):
    enabled: bool = True
    rows: list[MemAuditRow] = Field(default_factory=list)


class MemHealthResponse(BaseModel):
    enabled: bool
    healthy: bool


class MemStatusResponse(BaseModel):
    consolidating: bool


class RecallProbeRequest(BaseModel):
    learner_id: str
    query: str
    budget: int | None = None


class RecallSubgraph(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class RecallProbeResponse(BaseModel):
    enabled: bool = True
    text_block: str = ""
    subgraph: RecallSubgraph = Field(default_factory=RecallSubgraph)

def memory_router(
    get_host: Callable[[], EngramHost],
    *,
    learner_id_dep: Callable[..., Any],
    admin_dep: Callable[..., Any] | None = None,
    prefix: str = "/memory",
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["engram-memory"])

    def host_dep() -> EngramHost:
        return get_host()

    async def _graph(host: EngramHost, learner_id: str) -> dict:
        if not host.enabled:
            return {"enabled": False, "nodes": [], "edges": []}
        try:
            gv = await host.memory.graph(learner_id)
            return {"enabled": True, "nodes": gv.nodes, "edges": gv.edges}
        except Exception as exc:  # noqa: BLE001 — degrade, don't 500 (E5)
            logger.warning("memory graph failed for %s: %s", learner_id, exc)
            return {"enabled": False, "nodes": [], "edges": []}

    @router.get("/graph", response_model=MemGraphResponse)
    async def my_graph(learner_id: str = Depends(learner_id_dep),
                       host: EngramHost = Depends(host_dep)):
        return await _graph(host, learner_id)

    @router.get("/status", response_model=MemStatusResponse)
    async def my_status(learner_id: str = Depends(learner_id_dep),
                        host: EngramHost = Depends(host_dep)):
        return {"consolidating": host.is_consolidating(learner_id)}

    if admin_dep is not None:
        @router.get("/admin/graph", response_model=MemGraphResponse)
        async def admin_graph(learner_id: str, _: Any = Depends(admin_dep),
                              host: EngramHost = Depends(host_dep)):
            return await _graph(host, learner_id)

        @router.get("/admin/audit", response_model=MemAuditResponse)
        async def admin_audit(learner_id: str, limit: int = 100,
                              _: Any = Depends(admin_dep),
                              host: EngramHost = Depends(host_dep)):
            if not host.enabled:
                return {"enabled": False, "rows": []}
            try:
                rows = await host.memory.audit(learner_id, limit=limit)
                return {"enabled": True, "rows": rows}
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory audit failed for %s: %s", learner_id, exc)
                return {"enabled": False, "rows": []}

        @router.get("/admin/health", response_model=MemHealthResponse)
        async def admin_health(_: Any = Depends(admin_dep),
                               host: EngramHost = Depends(host_dep)):
            if not host.enabled:
                return {"enabled": False, "healthy": False}
            try:
                return {"enabled": True, "healthy": bool(await host.memory.health())}
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory health failed: %s", exc)
                return {"enabled": True, "healthy": False}

        @router.post("/admin/recall-probe", response_model=RecallProbeResponse)
        async def admin_recall_probe(req: RecallProbeRequest,
                                     _: Any = Depends(admin_dep),
                                     host: EngramHost = Depends(host_dep)):
            if not host.enabled:
                return {"enabled": False}
            try:
                res = await host.memory.recall(req.learner_id, req.query, req.budget)
                return {"enabled": True, "text_block": res.text_block,
                        "subgraph": res.subgraph}
            except Exception as exc:  # noqa: BLE001
                logger.warning("recall-probe failed for %s: %s", req.learner_id, exc)
                return {"enabled": False}

    return router
