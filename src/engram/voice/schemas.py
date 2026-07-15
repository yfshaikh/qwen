"""Pydantic response models for the voice-session HTTP surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
