"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from engram.core.models import (
    Completion,
    Edge,
    Evidence,
    LearningEvent,
    Message,
    Node,
)


_AUDIT_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
        self.mastery_history: list = []
        self.audit: list = []
        self._audit_rows: list[dict] = []
        self._audit_seq = 0
        self._locked: set[str] = set()
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"id-{self._seq}"

    async def health(self) -> bool:
        return self.healthy

    async def insert_event(self, e: LearningEvent) -> str:
        e.id = e.id or self._next_id()
        self.events.append(e)  # consolidated_at defaults to None on the dataclass
        return e.id

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

    async def get_pending_events(self, learner_id: str) -> list[LearningEvent]:
        return [
            e
            for e in self.events
            if e.learner_id == learner_id and e.consolidated_at is None
        ]

    async def get_live_nodes(self, learner_id: str) -> list[Node]:
        return [
            n
            for n in self.nodes.values()
            if n.learner_id == learner_id and n.forgotten_at is None
        ]

    @asynccontextmanager
    async def consolidation_lock(self, learner_id: str):
        if learner_id in self._locked:
            yield False
            return
        self._locked.add(learner_id)
        try:
            yield True
        finally:
            self._locked.discard(learner_id)

    async def apply_consolidation(self, plan) -> None:
        idmap: dict[str, str] = {}
        for n in plan.new_nodes:
            temp = n.id
            n.id = self._next_id()
            idmap[temp] = n.id
            self.nodes[n.id] = n

        def rid(x: str) -> str:
            return idmap.get(x, x)

        for e in plan.new_edges:
            e.id = e.id or self._next_id()
            e.source_id = rid(e.source_id)
            e.target_id = rid(e.target_id)
            self.edges.append(e)
        for ev in plan.new_evidence:
            ev.id = ev.id or self._next_id()
            ev.node_id = rid(ev.node_id)
            self.evidence.append(ev)
        for upd in plan.node_updates:
            existing = self.nodes.get(upd.id)
            if existing is not None:
                existing.mastery = upd.mastery
                existing.confidence = upd.confidence
                existing.salience = upd.salience
                existing.last_seen_at = upd.last_seen_at
                existing.forgotten_at = upd.forgotten_at
        for mp in plan.mastery_history:
            self.mastery_history.append((rid(mp.node_id), mp.mastery, mp.confidence))
        self.audit.extend(plan.audit)
        for a in plan.audit:
            self._audit_seq += 1
            self._audit_rows.append(
                {
                    "id": str(self._audit_seq),
                    "learner_id": plan.learner_id,
                    "op": a.op,
                    "rationale": a.rationale,
                    "model": a.model,
                    "tokens": a.tokens,
                    "cost": a.cost,
                    "ts": _AUDIT_BASE + timedelta(microseconds=self._audit_seq),
                }
            )
        if plan.processed_event_ids:
            stamp = datetime.now(timezone.utc)
            ids = set(plan.processed_event_ids)
            for e in self.events:
                if e.id in ids:
                    e.consolidated_at = stamp

    async def get_audit(self, learner_id: str, since=None, limit: int = 100) -> list[dict]:
        rows = [
            r
            for r in self._audit_rows
            if r["learner_id"] == learner_id and (since is None or r["ts"] > since)
        ]
        rows.sort(key=lambda r: r["ts"])
        keys = ("id", "op", "rationale", "model", "tokens", "cost", "ts")
        return [{k: r[k] for k in keys} for r in rows[:limit]]
