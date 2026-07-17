"""Engram — app-agnostic memory core for AI tutors.

This top level is the STABLE consumer API. `engram.core.*` and
`engram.adapters.*` are internal; hosts must not import them directly.

Which surface?

| Surface        | Use it for |
|-----------------|------------|
| `EngramHost`    | Production host runtime — construction never raises, `start()` catches and logs connect failures, `consolidate_soon()` runs consolidation in the background. |
| `Engram`        | The direct engine — wires storage/LLM/embedder and implements the memory verbs; embed it in-process, or drive it in tests. |
| `memory_router` | Optional FastAPI router (`engram.integrations.fastapi`) exposing the HTTP surface — mount it behind your own auth. |
"""

from __future__ import annotations

from engram.core.consolidation import ConsolidationReport
from engram.core.engram import Engram
from engram.core.ontology import (
    ConceptOntology,
    OntologyConcept,
    OntologyEdge,
    OntologyError,
)
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
from engram.runtime.host import DisabledEngram, EngramHost
from engram.runtime.factory import from_env

__version__ = "0.1.0"

__all__ = [
    "AuditRow", "ConceptOntology", "ConsolidationReport", "DisabledEngram",
    "Edge", "EdgeType", "Engram", "EngramHost", "Evidence", "EvidenceKind",
    "EvidenceRef", "GraphEdge", "GraphNode", "GraphView", "LearningEvent",
    "Node", "NodeType", "OntologyConcept", "OntologyEdge", "OntologyError",
    "RecallResult", "ScoredNode", "Subgraph", "SubgraphEdge", "from_env",
]
