"""Whiteboard HTTP routes: generate an SVG diagram panel on demand.

Auth-less like the rest of the console (accepted demo posture). Generation is
routed through the Engram LLM adapter's "diagram" role, which resolves to a GLM
model on the shared DashScope client (see Settings.model_diagram).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engram.app.deps import get_engram
from engram.whiteboard.generate import DiagramError, generate_panel

whiteboard_router = APIRouter(prefix="/whiteboard")


class PanelRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=2000)
    learner_id: str | None = None


class WhiteboardUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class PanelResponse(BaseModel):
    panel_id: str
    intent: str
    caption: str
    html: str
    anchors: list[str]
    model: str | None = None


@whiteboard_router.post("/panels", response_model=PanelResponse)
async def create_panel(req: PanelRequest, eng=Depends(get_engram)) -> PanelResponse:
    try:
        panel = await generate_panel(eng.llm, req.intent)
    except DiagramError as exc:
        # The model ran but produced no drawable SVG — a 422 (semantic), not a
        # 500. The client shows its "that sketch didn't come out" fallback.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PanelResponse(
        panel_id=panel.panel_id,
        intent=panel.intent,
        caption=panel.caption,
        html=panel.html,
        anchors=panel.anchors,
        model=panel.model,
    )
