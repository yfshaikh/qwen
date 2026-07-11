"""Pure domain types. No I/O, no third-party imports beyond stdlib + dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NodeType(str, Enum):
    CONCEPT = "concept"
    PREFERENCE = "preference"
    GOAL = "goal"


class EdgeType(str, Enum):
    PREREQUISITE = "prerequisite"
    RELATES_TO = "relates_to"
    PART_OF = "part_of"


class EvidenceKind(str, Enum):
    EXPLAINED = "explained"
    ASKED_ABOUT = "asked_about"
    QUIZ_CORRECT = "quiz_correct"
    QUIZ_WRONG = "quiz_wrong"
    NOTE = "note"
    STRUGGLE = "struggle"
    DEMONSTRATED = "demonstrated"


@dataclass(slots=True)
class LearningEvent:
    learner_id: str
    type: str
    text: str | None = None
    refs: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=_now)
    consolidated_at: datetime | None = None
    id: str | None = None


@dataclass(slots=True)
class Node:
    learner_id: str
    type: NodeType
    label: str
    id: str | None = None
    summary: str | None = None
    mastery: float | None = None
    confidence: float | None = None
    salience: float | None = None
    importance: float | None = None
    embedding: list[float] | None = None
    source_refs: list[Any] = field(default_factory=list)
    forgotten_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    last_seen_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Edge:
    learner_id: str
    source_id: str
    target_id: str
    type: EdgeType
    id: str | None = None
    weight: float = 1.0
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Evidence:
    node_id: str
    kind: EvidenceKind
    id: str | None = None
    content: str | None = None
    source_ref: dict[str, Any] | None = None
    embedding: list[float] | None = None
    importance: float | None = None
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass(slots=True)
class Completion:
    text: str | None = None
    json: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


@dataclass(slots=True)
class RecallResult:
    text_block: str
    subgraph: dict[str, Any]


@dataclass(slots=True)
class GraphView:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
