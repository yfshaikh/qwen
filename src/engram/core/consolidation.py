"""Planner↔storage contract types for consolidation.

The planner produces a ConsolidationPlan (intended changes); storage applies it
atomically. New nodes carry temp ids ("tmp-N") remapped to real ids at commit, so
edges/evidence/mastery_history reference nodes by id string (temp or real).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engram.core.models import Edge, Evidence, Node


@dataclass(slots=True)
class AuditEntry:
    op: str  # extract|link|merge|resolve_contradiction|decay|prune|consolidate|extract_failed
    rationale: str | None = None
    input_refs: Any = None
    output_refs: Any = None
    model: str | None = None
    tokens: int | None = None
    cost: float | None = None


@dataclass(slots=True)
class MasteryPoint:
    node_id: str  # temp or real
    mastery: float | None
    confidence: float | None


@dataclass(slots=True)
class ConsolidationPlan:
    learner_id: str
    new_nodes: list[Node] = field(default_factory=list)        # id is a temp "tmp-N"
    node_updates: list[Node] = field(default_factory=list)     # existing real id
    new_edges: list[Edge] = field(default_factory=list)        # ids temp or real
    new_evidence: list[Evidence] = field(default_factory=list)  # node_id temp or real
    mastery_history: list[MasteryPoint] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
    processed_event_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConsolidationReport:
    learner_id: str
    processed_events: int = 0
    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    merged: int = 0
    forgotten: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: bool = False
