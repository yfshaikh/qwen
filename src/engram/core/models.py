"""Pure domain types. No I/O, no third-party imports beyond stdlib + dataclasses.

Shape rule (see `engram.core.wire` for the full statement): dataclasses here
are the in-process domain objects; the TypedDicts below (`GraphNode`,
`GraphEdge`, `AuditRow`, `ScoredNode`, ...) type storage *read-output*
shapes as plain dicts. The HTTP wire versions of `GraphNode`/`GraphEdge`/
`AuditRow` are Pydantic models defined once in `engram.core.wire` — that
module is the wire source of truth; these TypedDicts intentionally mirror
its field names/shapes but are not themselves imported by the wire layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict


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


# --- typed shapes for the dict-valued returns (consumer SDK) -----------------
# TypedDicts, not dataclasses: runtime objects stay plain dicts so JSON wire
# shapes and existing dict-style consumers are untouched; only checkers see them.


class EvidenceRef(TypedDict):
    kind: str
    content: str | None
    importance: float | None


class ScoredNode(TypedDict):
    id: str | None
    type: str
    label: str
    mastery: float | None
    confidence: float | None
    salience: float | None
    importance: float | None
    score: float
    scores: dict[str, float]
    evidence: list[EvidenceRef]


class SubgraphEdge(TypedDict):
    id: str | None
    source: str
    target: str
    type: str
    weight: float


class Subgraph(TypedDict):
    nodes: list[ScoredNode]
    edges: list[SubgraphEdge]


class GraphNode(TypedDict):
    id: str | None
    label: str
    type: str
    summary: str | None
    mastery: float | None
    confidence: float | None
    salience: float | None
    importance: float | None
    evidence: list[EvidenceRef]


class GraphEdge(TypedDict):
    id: str | None
    source: str
    target: str
    type: str
    weight: float


class AuditRow(TypedDict):
    id: str
    op: str
    rationale: str | None
    model: str | None
    tokens: int | None
    cost: float | None
    ts: Any  # datetime from storage; hosts/HTTP layers serialize


@dataclass(slots=True)
class RecallResult:
    text_block: str
    subgraph: Subgraph


@dataclass(slots=True)
class GraphView:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --- shared field-projection helpers (kill the recall.py/graph.py copy-paste) -


def evidence_ref(e: Evidence) -> EvidenceRef:
    return {"kind": e.kind.value, "content": e.content, "importance": e.importance}


def node_common_fields(n: Node) -> dict[str, Any]:
    """Fields shared by ScoredNode (recall.py) and GraphNode (graph.py).

    Each caller layers its own extra keys (score/scores for recall,
    summary for graph) on top of this dict.
    """
    return {
        "id": n.id,
        "label": n.label,
        "type": n.type.value,
        "mastery": n.mastery,
        "confidence": n.confidence,
        "salience": n.salience,
        "importance": n.importance,
    }
