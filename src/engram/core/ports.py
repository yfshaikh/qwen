"""The agnostic surface. Protocols only — no third-party imports, no bodies.

These three ports are the entire seam between Engram's core and the outside
world. Adapters (Postgres, OpenRouter, in-memory) implement them structurally;
the core depends only on these signatures.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from engram.core.models import (
    AuditEntry,
    Completion,
    Edge,
    Evidence,
    GraphView,
    LearningEvent,
    Message,
    Node,
    RecallResult,
)


@runtime_checkable
class LLMPort(Protocol):
    """Model access, tiered by role (tutor|extractor|reflector|embedder)."""

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class StoragePort(Protocol):
    """Persistence for the knowledge graph + append-only streams.

    Two concrete implementations: `PostgresStorage` (asyncpg + pgvector) for the
    real app, and `InMemoryStorage` for tests/eval/quick demos. They MUST behave
    identically for the methods below.
    """

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def health(self) -> bool: ...

    # --- Events (append-only raw input + Keeper queue) ---
    async def insert_event(self, e: LearningEvent) -> str: ...
    async def insert_events(self, events: list[LearningEvent]) -> list[str]: ...
    async def fetch_unconsolidated_events(
        self, learner_id: str, limit: int = 1000
    ) -> list[LearningEvent]: ...
    async def mark_events_consolidated(
        self, event_ids: list[str], ts: datetime | None = None
    ) -> None: ...
    async def count_pending_events(self, learner_id: str) -> int: ...
    async def learners_with_pending_events(
        self, quiet_for_seconds: int = 0
    ) -> list[str]: ...

    # --- Nodes ---
    async def upsert_node(self, node: Node) -> str: ...
    async def get_node(self, node_id: str) -> Node | None: ...
    async def get_nodes(
        self,
        learner_id: str,
        types: list[str] | None = None,
        include_forgotten: bool = False,
    ) -> list[Node]: ...
    async def vector_search(
        self,
        learner_id: str,
        query_vec: list[float],
        k: int,
        types: list[str] | None = None,
    ) -> list[tuple[Node, float]]:
        """Return up to k (node, cosine_similarity) pairs, most similar first."""
        ...

    async def update_node_state(
        self,
        node_id: str,
        *,
        mastery: float | None = None,
        confidence: float | None = None,
        salience: float | None = None,
        last_seen_at: datetime | None = None,
        forgotten_at: datetime | None = None,
        summary: str | None = None,
        embedding: list[float] | None = None,
    ) -> None: ...
    async def delete_node(self, node_id: str) -> None: ...

    # --- Edges ---
    async def upsert_edge(self, edge: Edge) -> str: ...
    async def get_edges(
        self, learner_id: str, node_ids: list[str] | None = None
    ) -> list[Edge]: ...

    # --- Evidence ---
    async def insert_evidence(self, ev: Evidence) -> str: ...
    async def get_evidence(self, node_id: str, limit: int = 50) -> list[Evidence]: ...
    async def evidence_counts(self, node_ids: list[str]) -> dict[str, int]: ...

    # --- Audit + mastery history (observability) ---
    async def insert_audit(self, entry: AuditEntry) -> str: ...
    async def get_audit(self, learner_id: str, limit: int = 100) -> list[AuditEntry]: ...
    async def insert_mastery_snapshot(
        self,
        node_id: str,
        mastery: float | None,
        confidence: float | None,
        ts: datetime | None = None,
    ) -> None: ...
    async def get_mastery_history(
        self, node_id: str
    ) -> list[tuple[datetime, float | None, float | None]]: ...


@runtime_checkable
class HostPort(Protocol):
    """The core's outward API surface, consumed by host adapters (voice/text)."""

    async def ingest(self, events: list[LearningEvent]) -> list[str]: ...
    async def recall(
        self, learner_id: str, query: str, budget: int = 600
    ) -> RecallResult: ...
    async def consolidate(self, learner_id: str) -> dict[str, Any]: ...
    async def graph(
        self, learner_id: str, focus: str | None = None, hops: int = 1
    ) -> GraphView: ...
