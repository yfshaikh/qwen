"""Pydantic response models for the insights HTTP surface."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class InsightsSummary(BaseModel):
    concepts: int
    edges: int
    evidence: int
    avg_mastery: float | None = None
    avg_confidence: float | None = None
    forgotten: int
    fading: int
    open_misconceptions: int
    sessions: int
    last_active: datetime | None = None


class MasteryPoint(BaseModel):
    ts: datetime | None = None
    mastery: float | None = None
    confidence: float | None = None


class MasteryTimelineResponse(BaseModel):
    series: dict[str, list[MasteryPoint]] = Field(default_factory=dict)


class Hotspot(BaseModel):
    node_id: str
    label: str
    struggle: int
    mastery: float | None = None
    trend: str


class HotspotsResponse(BaseModel):
    hotspots: list[Hotspot] = Field(default_factory=list)


class ActivityDay(BaseModel):
    day: date
    count: int


class ActivityResponse(BaseModel):
    days: list[ActivityDay] = Field(default_factory=list)


class ReviewItem(BaseModel):
    node_id: str
    label: str
    score: float
    reason: str


class ReviewQueueResponse(BaseModel):
    items: list[ReviewItem] = Field(default_factory=list)


class Blocker(BaseModel):
    node_id: str
    label: str
    mastery: float
    path: list[str] = Field(default_factory=list)


class BlockersResponse(BaseModel):
    blockers: list[Blocker] = Field(default_factory=list)
