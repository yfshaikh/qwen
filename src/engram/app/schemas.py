"""Pydantic request/response models for the HTTP service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    learner_id: str
    type: str
    text: str | None = None
    refs: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)


class AddRequest(BaseModel):
    events: list[EventIn]


class AddResponse(BaseModel):
    ingested: int


class RecallRequest(BaseModel):
    learner_id: str
    query: str
    budget: int | None = None


class RecallResponse(BaseModel):
    text_block: str
    subgraph: dict[str, Any]


class ConsolidateRequest(BaseModel):
    learner_id: str


class ReportOut(BaseModel):
    learner_id: str
    processed_events: int
    nodes_created: int
    nodes_updated: int
    edges_created: int
    merged: int
    forgotten: int
    errors: list[str]
    skipped: bool


class AuditRow(BaseModel):
    id: str
    op: str
    rationale: str | None = None
    model: str | None = None
    tokens: int | None = None
    cost: float | None = None
    ts: datetime


class AuditResponse(BaseModel):
    rows: list[AuditRow]
    cursor: datetime | None = None


class HealthResponse(BaseModel):
    status: str
    db: bool


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    learner_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    budget: int | None = None


class GraphEvidence(BaseModel):
    kind: str
    content: str | None = None
    importance: float | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    summary: str | None = None
    mastery: float | None = None
    confidence: float | None = None
    salience: float | None = None
    importance: float | None = None
    evidence: list[GraphEvidence] = Field(default_factory=list)


class GraphEdge(BaseModel):
    id: str | None = None
    source: str
    target: str
    type: str
    weight: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HistoryResponse(BaseModel):
    messages: list[ChatMessage]


class VoiceSessionOut(BaseModel):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    turns: int = 0


class SessionsResponse(BaseModel):
    sessions: list[VoiceSessionOut]


class VoiceTurnOut(BaseModel):
    id: str
    role: str
    text: str
    ts: datetime | None = None


class TurnsResponse(BaseModel):
    turns: list[VoiceTurnOut]


class MemoryStatusResponse(BaseModel):
    consolidating: bool
