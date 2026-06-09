"""In-memory StoragePort implementation.

A faithful, dependency-light twin of `PostgresStorage` used by unit tests, the
eval harness, and `ENGRAM_STORAGE_BACKEND=memory` quick demos. Reads return deep
copies so callers can't mutate stored state (mimicking a real DB round-trip).
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

from engram.core.models import AuditEntry, Edge, Evidence, LearningEvent, Node


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _type_str(t: object) -> str:
    return t.value if hasattr(t, "value") else str(t)


class InMemoryStorage:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self._events: dict[str, LearningEvent] = {}
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._evidence: dict[str, Evidence] = {}
        self._audit: list[AuditEntry] = []
        self._mastery: list[tuple[str, datetime, float | None, float | None]] = []

    async def connect(self) -> None:  # no-op
        return None

    async def close(self) -> None:  # no-op
        return None

    async def health(self) -> bool:
        return self.healthy

    # --- Events ---
    async def insert_event(self, e: LearningEvent) -> str:
        eid = e.id or _uuid()
        stored = copy.deepcopy(e)
        stored.id = eid
        self._events[eid] = stored
        return eid

    async def insert_events(self, events: list[LearningEvent]) -> list[str]:
        return [await self.insert_event(e) for e in events]

    async def fetch_unconsolidated_events(
        self, learner_id: str, limit: int = 1000
    ) -> list[LearningEvent]:
        rows = [
            e
            for e in self._events.values()
            if e.learner_id == learner_id and e.consolidated_at is None
        ]
        rows.sort(key=lambda e: e.ts)
        return [copy.deepcopy(e) for e in rows[:limit]]

    async def mark_events_consolidated(
        self, event_ids: list[str], ts: datetime | None = None
    ) -> None:
        ts = ts or _now()
        for eid in event_ids:
            if eid in self._events:
                self._events[eid].consolidated_at = ts

    async def count_pending_events(self, learner_id: str) -> int:
        return sum(
            1
            for e in self._events.values()
            if e.learner_id == learner_id and e.consolidated_at is None
        )

    async def learners_with_pending_events(self, quiet_for_seconds: int = 0) -> list[str]:
        cutoff = _now() - timedelta(seconds=quiet_for_seconds)
        latest: dict[str, datetime] = {}
        pending: set[str] = set()
        for e in self._events.values():
            if e.consolidated_at is None:
                pending.add(e.learner_id)
            prev = latest.get(e.learner_id)
            if prev is None or e.ts > prev:
                latest[e.learner_id] = e.ts
        return sorted(
            lid for lid in pending if quiet_for_seconds == 0 or latest[lid] <= cutoff
        )

    # --- Nodes ---
    async def upsert_node(self, node: Node) -> str:
        nid = node.id or _uuid()
        stored = copy.deepcopy(node)
        stored.id = nid
        self._nodes[nid] = stored
        return nid

    async def get_node(self, node_id: str) -> Node | None:
        n = self._nodes.get(node_id)
        return copy.deepcopy(n) if n else None

    async def get_nodes(
        self,
        learner_id: str,
        types: list[str] | None = None,
        include_forgotten: bool = False,
    ) -> list[Node]:
        out = []
        for n in self._nodes.values():
            if n.learner_id != learner_id:
                continue
            if types is not None and _type_str(n.type) not in types:
                continue
            if not include_forgotten and n.forgotten_at is not None:
                continue
            out.append(copy.deepcopy(n))
        out.sort(key=lambda n: (n.salience or 0.0), reverse=True)
        return out

    async def vector_search(
        self,
        learner_id: str,
        query_vec: list[float],
        k: int,
        types: list[str] | None = None,
    ) -> list[tuple[Node, float]]:
        scored: list[tuple[Node, float]] = []
        for n in self._nodes.values():
            if n.learner_id != learner_id or n.embedding is None or n.forgotten_at is not None:
                continue
            if types is not None and _type_str(n.type) not in types:
                continue
            scored.append((copy.deepcopy(n), _cosine(query_vec, n.embedding)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

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
    ) -> None:
        n = self._nodes.get(node_id)
        if n is None:
            return
        if mastery is not None:
            n.mastery = mastery
        if confidence is not None:
            n.confidence = confidence
        if salience is not None:
            n.salience = salience
        if last_seen_at is not None:
            n.last_seen_at = last_seen_at
        if forgotten_at is not None:
            n.forgotten_at = forgotten_at
        if summary is not None:
            n.summary = summary
        if embedding is not None:
            n.embedding = list(embedding)

    async def delete_node(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)
        self._edges = {
            k: e
            for k, e in self._edges.items()
            if e.source_id != node_id and e.target_id != node_id
        }
        self._evidence = {
            k: ev for k, ev in self._evidence.items() if ev.node_id != node_id
        }

    # --- Edges ---
    async def upsert_edge(self, edge: Edge) -> str:
        # Dedupe on (learner, source, target, type).
        for existing in self._edges.values():
            if (
                existing.learner_id == edge.learner_id
                and existing.source_id == edge.source_id
                and existing.target_id == edge.target_id
                and existing.type == edge.type
            ):
                if edge.weight is not None:
                    existing.weight = edge.weight
                return existing.id  # type: ignore[return-value]
        eid = edge.id or _uuid()
        stored = copy.deepcopy(edge)
        stored.id = eid
        self._edges[eid] = stored
        return eid

    async def get_edges(
        self, learner_id: str, node_ids: list[str] | None = None
    ) -> list[Edge]:
        ids = set(node_ids) if node_ids is not None else None
        out = []
        for e in self._edges.values():
            if e.learner_id != learner_id:
                continue
            if ids is not None and e.source_id not in ids and e.target_id not in ids:
                continue
            out.append(copy.deepcopy(e))
        return out

    # --- Evidence ---
    async def insert_evidence(self, ev: Evidence) -> str:
        eid = ev.id or _uuid()
        stored = copy.deepcopy(ev)
        stored.id = eid
        self._evidence[eid] = stored
        return eid

    async def get_evidence(self, node_id: str, limit: int = 50) -> list[Evidence]:
        rows = [ev for ev in self._evidence.values() if ev.node_id == node_id]
        rows.sort(key=lambda ev: ev.created_at, reverse=True)
        return [copy.deepcopy(ev) for ev in rows[:limit]]

    async def evidence_counts(self, node_ids: list[str]) -> dict[str, int]:
        counts = {nid: 0 for nid in node_ids}
        wanted = set(node_ids)
        for ev in self._evidence.values():
            if ev.node_id in wanted:
                counts[ev.node_id] += 1
        return counts

    # --- Audit + mastery history ---
    async def insert_audit(self, entry: AuditEntry) -> str:
        aid = entry.id or _uuid()
        stored = copy.deepcopy(entry)
        stored.id = aid
        self._audit.append(stored)
        return aid

    async def get_audit(self, learner_id: str, limit: int = 100) -> list[AuditEntry]:
        rows = [a for a in self._audit if a.learner_id == learner_id]
        rows.sort(key=lambda a: a.ts, reverse=True)
        return [copy.deepcopy(a) for a in rows[:limit]]

    async def insert_mastery_snapshot(
        self,
        node_id: str,
        mastery: float | None,
        confidence: float | None,
        ts: datetime | None = None,
    ) -> None:
        self._mastery.append((node_id, ts or _now(), mastery, confidence))

    async def get_mastery_history(
        self, node_id: str
    ) -> list[tuple[datetime, float | None, float | None]]:
        rows = [(ts, m, c) for (nid, ts, m, c) in self._mastery if nid == node_id]
        rows.sort(key=lambda r: r[0])
        return rows
