"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

import math
from typing import Any

from engram.core.models import (
    Completion,
    Edge,
    Evidence,
    LearningEvent,
    Message,
    Node,
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class FakeLLM:
    def __init__(self, canned_text: str = "ok") -> None:
        self.canned_text = canned_text
        self.complete_calls: list[tuple[str, list[Message], dict | None]] = []

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        self.complete_calls.append((role, messages, schema))
        return Completion(
            text=self.canned_text, usage={"role": role}, model=f"fake-{role}"
        )


class FakeEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.embed_calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        # Deterministic, text-derived vector so tests are stable.
        return [[float(len(t) % 7)] * self.dim for t in texts]


class FakeStorage:
    """In-memory graph implementing StoragePort for offline tests."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.events: list[LearningEvent] = []
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.evidence: list[Evidence] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"id-{self._seq}"

    async def health(self) -> bool:
        return self.healthy

    async def insert_event(self, e: LearningEvent) -> str:
        self.events.append(e)  # consolidated_at defaults to None on the dataclass
        return self._next_id()

    async def insert_events(self, events: list[LearningEvent]) -> list[str]:
        return [await self.insert_event(e) for e in events]

    async def insert_node(self, n: Node) -> str:
        n.id = n.id or self._next_id()
        self.nodes[n.id] = n
        return n.id

    async def insert_edge(self, e: Edge) -> str:
        e.id = e.id or self._next_id()
        self.edges.append(e)
        return e.id

    async def insert_evidence(self, ev: Evidence) -> str:
        ev.id = ev.id or self._next_id()
        self.evidence.append(ev)
        return ev.id

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        live = [
            n
            for n in self.nodes.values()
            if n.learner_id == learner_id
            and n.forgotten_at is None
            and n.embedding is not None
        ]
        live.sort(key=lambda n: _cosine(query_vec, n.embedding), reverse=True)
        return live[:k]

    async def get_edges(self, learner_id: str, node_ids: list[str]) -> list[Edge]:
        ids = set(node_ids)
        return [
            e
            for e in self.edges
            if e.learner_id == learner_id and (e.source_id in ids or e.target_id in ids)
        ]

    async def get_nodes(self, learner_id: str, node_ids: list[str]) -> list[Node]:
        ids = set(node_ids)
        return [
            n
            for n in self.nodes.values()
            if n.learner_id == learner_id and n.id in ids and n.forgotten_at is None
        ]

    async def top_evidence(
        self, node_ids: list[str], per_node: int
    ) -> dict[str, list[Evidence]]:
        out: dict[str, list[Evidence]] = {}
        for nid in node_ids:
            evs = [ev for ev in self.evidence if ev.node_id == nid]
            evs.sort(key=lambda e: (e.importance or 0.0), reverse=True)
            out[nid] = evs[:per_node]
        return out
