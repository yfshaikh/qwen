"""The agnostic surface. Protocols only — no third-party imports, no bodies.

LLMPort and EmbedderPort are deliberately separate: the chat provider
(OpenRouter) and the embeddings provider (OpenAI) are different services in this
build. Splitting them lets each be swapped independently (e.g. DashScope later).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

from engram.core.consolidation import ConsolidationPlan
from engram.core.models import (
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
        self, node_ids: list[str], per_node: int
    ) -> dict[str, list[Evidence]]: ...
    async def get_events(
        self, learner_id: str, limit: int = 200
    ) -> list[LearningEvent]: ...

    # consolidation (Phase 2)
    async def get_pending_events(self, learner_id: str) -> list[LearningEvent]: ...
    async def get_live_nodes(self, learner_id: str) -> list[Node]: ...
    def consolidation_lock(
        self, learner_id: str
    ) -> AbstractAsyncContextManager[bool]: ...
    async def apply_consolidation(self, plan: ConsolidationPlan) -> None: ...
    async def get_audit(
        self, learner_id: str, since: Any = None, limit: int = 100
    ) -> list[dict]: ...


@runtime_checkable
class HostPort(Protocol):
    """The core's outward API surface (consumed by host adapters).

    Sketched in Phase 0; bodies land in Phases 1–2.
    """

    async def ingest(self, events: list[LearningEvent]) -> None: ...
    async def recall(
        self, learner_id: str, query: str, budget: int
    ) -> RecallResult: ...
    async def consolidate(self, learner_id: str) -> None: ...
    async def graph(
        self, learner_id: str, focus: str | None = None
    ) -> GraphView: ...
