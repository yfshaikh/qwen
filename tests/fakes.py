"""In-process fakes implementing the core Protocols. Used by all non-live tests.

`FakeStorage` is the functional `InMemoryStorage` (full StoragePort). `FakeLLM`
returns canned output by default, or you can pass a `responder` to script
per-call completions (used by Keeper extraction tests) and/or an `embedder`
(e.g. `HashingEmbedder`) for realistic vectors in recall tests.
"""

from __future__ import annotations

from typing import Any, Callable

from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import Completion, Message

# The functional in-memory store is our storage fake.
FakeStorage = InMemoryStorage


class FakeLLM:
    def __init__(
        self,
        canned_text: str = "ok",
        canned_embedding: list[float] | None = None,
        dim: int = 1024,
        responder: Callable[[str, list[Message], dict | None], Completion] | None = None,
        embedder: Any | None = None,
    ) -> None:
        self.canned_text = canned_text
        self.canned_embedding = canned_embedding or [0.0] * dim
        self.responder = responder
        self.embedder = embedder
        self.complete_calls: list[tuple[str, list[Message], dict | None]] = []
        self.embed_calls: list[list[str]] = []

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        self.complete_calls.append((role, messages, schema))
        if self.responder is not None:
            return self.responder(role, messages, schema)
        return Completion(text=self.canned_text, usage={"role": role}, model=f"fake-{role}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        if self.embedder is not None:
            return await self.embedder.embed(texts)
        return [list(self.canned_embedding) for _ in texts]
