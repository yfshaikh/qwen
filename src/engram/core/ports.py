"""The agnostic surface. Protocols only — no third-party imports, no bodies.

LLMPort and EmbedderPort are deliberately separate so chat and embeddings can
be swapped independently. Both currently point at DashScope's OpenAI-compatible
endpoint (Qwen models), but nothing here assumes that.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from engram.core.consolidation import ConsolidationPlan
from engram.core.models import (
    Completion,
    Edge,
    Evidence,
    LearningEvent,
    Message,
    Node,
)


@runtime_checkable
class LLMPort(Protocol):
    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion: ...

    def stream(self, role: str, messages: list[Message]) -> AsyncIterator[str]: ...


@runtime_checkable
class EmbedderPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class StoragePort(Protocol):
    # lifecycle (folded in rather than a separate Lifecycle protocol — every
    # consumer that needs one storage method needs both)
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    async def health(self) -> bool: ...

    # writes
    async def insert_event(self, e: LearningEvent) -> str: ...
    async def insert_events(self, events: list[LearningEvent]) -> list[str]: ...
    async def insert_node(self, n: Node) -> str: ...
    async def insert_edge(self, e: Edge) -> str: ...
    async def insert_evidence(self, ev: Evidence) -> str: ...
    async def delete_learner(self, learner_id: str) -> None: ...

    # reads
    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]: ...
    async def get_edges(self, learner_id: str, node_ids: list[str]) -> list[Edge]: ...
    async def get_nodes(self, learner_id: str, node_ids: list[str]) -> list[Node]: ...
    async def top_evidence(
        self, node_ids: list[str], per_node: int, *, with_embedding: bool = True
    ) -> dict[str, list[Evidence]]: ...
    async def get_events(
        self, learner_id: str, limit: int = 200
    ) -> list[LearningEvent]: ...

    # consolidation (Phase 2)
    async def get_pending_events(
        self, learner_id: str, *, limit: int | None = None
    ) -> list[LearningEvent]: ...
    async def get_live_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]: ...
    async def get_all_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]: ...
    def consolidation_lock(
        self, learner_id: str
    ) -> AbstractAsyncContextManager[bool]: ...
    async def apply_consolidation(self, plan: ConsolidationPlan) -> None: ...
    async def apply_ontology(
        self, learner_id: str, nodes: list[Node], edges: list[Edge]
    ) -> dict: ...
    async def merge_nodes(
        self,
        learner_id: str,
        keep_id: str,
        drop_id: str,
        *,
        label: str,
        mastery: float | None,
        confidence: float | None,
        salience: float | None,
        importance: float | None,
        rationale: str,
    ) -> None: ...
    async def get_audit(
        self, learner_id: str, since: Any = None, limit: int = 100
    ) -> list[dict]: ...


@runtime_checkable
class VoiceStore(Protocol):
    """Voice-session persistence (host-layer passthroughs on Engram)."""

    async def create_voice_session(self, learner_id: str) -> str: ...
    async def end_voice_session(self, session_id: str) -> None: ...
    async def append_voice_turn(
        self, session_id: str, learner_id: str, role: str, text: str
    ) -> str: ...
    async def list_voice_sessions(
        self, learner_id: str, limit: int = 50
    ) -> list[dict]: ...
    async def list_voice_turns(self, session_id: str) -> list[dict]: ...
    async def count_voice_sessions(self, learner_id: str) -> int: ...


@runtime_checkable
class InsightsStore(Protocol):
    """The read-only surface `insights.Insights` needs. A structural subset of
    StoragePort (get_all_nodes/get_live_nodes/get_edges) and VoiceStore
    (count_voice_sessions) duplicated here rather than inherited, so this
    protocol stays narrow and read-only — plus the insight-specific
    aggregation queries below, which live nowhere else."""

    async def get_all_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]: ...
    async def get_live_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]: ...
    async def get_edges(self, learner_id: str, node_ids: list[str]) -> list[Edge]: ...
    async def count_voice_sessions(self, learner_id: str) -> int: ...

    async def mastery_history(
        self,
        learner_id: str,
        node_ids: list[str] | None = None,
        since: datetime | None = None,
    ) -> list[dict]: ...
    async def evidence_counts_by_kind(self, learner_id: str) -> list[dict]: ...
    async def event_counts_by_day(self, learner_id: str, days: int = 30) -> list[dict]: ...
    async def last_event_at(self, learner_id: str) -> datetime | None: ...
