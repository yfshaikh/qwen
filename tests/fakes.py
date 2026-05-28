"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

from typing import Any

from engram.core.models import Completion, LearningEvent, Message, Node


class FakeLLM:
    def __init__(
        self,
        canned_text: str = "ok",
        canned_embedding: list[float] | None = None,
    ) -> None:
        self.canned_text = canned_text
        self.canned_embedding = canned_embedding or [0.0] * 1024
        self.complete_calls: list[tuple[str, list[Message], dict | None]] = []
        self.embed_calls: list[list[str]] = []

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        self.complete_calls.append((role, messages, schema))
        return Completion(text=self.canned_text, usage={"role": role}, model=f"fake-{role}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        return [list(self.canned_embedding) for _ in texts]


class FakeStorage:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    async def health(self) -> bool:
        return self.healthy

    async def insert_event(self, e: LearningEvent) -> str:
        raise NotImplementedError("Phase 1")

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        raise NotImplementedError("Phase 1")
