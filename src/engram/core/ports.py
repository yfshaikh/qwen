"""The agnostic surface. Protocols only — no third-party imports, no bodies."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from engram.core.models import (
    Completion,
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

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class StoragePort(Protocol):
    async def health(self) -> bool: ...

    # The remainder is the surface Phases 1–2 implement. Declared here so
    # adapters and fakes know what's coming and signatures stay stable.
    async def insert_event(self, e: LearningEvent) -> str: ...
    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]: ...


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
