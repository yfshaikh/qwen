"""Engram — app-agnostic memory core for AI tutors.

This top level is the STABLE consumer API. `engram.core.*` and
`engram.adapters.*` are internal; hosts must not import them directly.
"""

from __future__ import annotations

from engram.core.consolidation import ConsolidationReport
from engram.core.engram import Engram
from engram.core.models import (
    AuditRow,
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    GraphEdge,
    GraphNode,
    GraphView,
    LearningEvent,
    Node,
    NodeType,
    RecallResult,
    ScoredNode,
    Subgraph,
    SubgraphEdge,
)
from engram.host import DisabledEngram, EngramHost

__version__ = "0.1.0"

__all__ = [
    "AuditRow", "ConsolidationReport", "DisabledEngram", "Edge", "EdgeType",
    "Engram", "EngramHost", "Evidence", "EvidenceKind", "EvidenceRef",
    "GraphEdge", "GraphNode", "GraphView", "LearningEvent", "Node", "NodeType",
    "RecallResult", "ScoredNode", "Subgraph", "SubgraphEdge",
]
