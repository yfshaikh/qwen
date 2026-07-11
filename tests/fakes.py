"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from engram.core.edges import edge_rank
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
        self.stream_calls: list[tuple[str, list[Message]]] = []

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

    async def stream(self, role: str, messages: list[Message]):
        self.stream_calls.append((role, messages))
        text = self.canned_text
        mid = len(text) // 2
        for chunk in (text[:mid], text[mid:]):
            if chunk:
                yield chunk


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
        self.voice_sessions: dict[str, dict] = {}
        self.voice_turns: list[dict] = []

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

    def _assert_unique_pair(self, e: Edge) -> None:
        # Mirrors migration 0004's unique index engram_edges_undirected_pair:
        # one edge per undirected node pair per learner. Postgres raises
        # asyncpg.UniqueViolationError; the fake raises ValueError.
        pair = frozenset((e.source_id, e.target_id))
        if any(ex.learner_id == e.learner_id
               and frozenset((ex.source_id, ex.target_id)) == pair
               for ex in self.edges):
            raise ValueError(
                f"duplicate edge pair {e.source_id}~{e.target_id} for {e.learner_id}")

    async def insert_edge(self, e: Edge) -> str:
        self._assert_unique_pair(e)
        e.id = e.id or self._next_id()
        self.edges.append(e)
        return e.id

    async def insert_evidence(self, ev: Evidence) -> str:
        ev.id = ev.id or self._next_id()
        self.evidence.append(ev)
        return ev.id

    async def delete_learner(self, learner_id: str) -> None:
        dead = {nid for nid, n in self.nodes.items() if n.learner_id == learner_id}
        self.nodes = {nid: n for nid, n in self.nodes.items() if nid not in dead}
        self.edges = [e for e in self.edges if e.learner_id != learner_id]
        self.evidence = [ev for ev in self.evidence if ev.node_id not in dead]
        self.events = [e for e in self.events if e.learner_id != learner_id]
        self.mastery_history = [m for m in self.mastery_history if m[0] not in dead]
        self._audit_rows = [r for r in self._audit_rows if r["learner_id"] != learner_id]
        dead_sessions = {sid for sid, s in self.voice_sessions.items()
                         if s["learner_id"] == learner_id}
        self.voice_sessions = {sid: s for sid, s in self.voice_sessions.items()
                               if sid not in dead_sessions}
        self.voice_turns = [t for t in self.voice_turns if t["learner_id"] != learner_id]

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

    async def get_pending_events(
        self, learner_id: str, *, limit: int | None = None
    ) -> list[LearningEvent]:
        evs = [
            e
            for e in self.events
            if e.learner_id == learner_id and e.consolidated_at is None
        ]
        evs.sort(key=lambda e: e.ts)
        if limit is not None:
            evs = evs[-limit:]
        return evs

    async def get_events(
        self, learner_id: str, limit: int = 200
    ) -> list[LearningEvent]:
        evs = sorted(
            (e for e in self.events if e.learner_id == learner_id),
            key=lambda e: e.ts,
        )
        return evs[-limit:]

    async def get_live_nodes(self, learner_id: str) -> list[Node]:
        return [
            n
            for n in self.nodes.values()
            if n.learner_id == learner_id and n.forgotten_at is None
        ]

    async def get_all_nodes(self, learner_id: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.learner_id == learner_id]

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
            e.source_id = rid(e.source_id)
            e.target_id = rid(e.target_id)
            self._assert_unique_pair(e)
            e.id = e.id or self._next_id()
            self.edges.append(e)
        for upd in plan.edge_updates:
            for e in self.edges:
                if e.id == upd.id:
                    e.type, e.weight = upd.type, upd.weight
                    e.source_id, e.target_id = upd.source_id, upd.target_id
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
                existing.importance = upd.importance
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

    async def merge_nodes(self, learner_id, keep_id, drop_id, *, mastery,
                          confidence, salience, importance, rationale) -> None:
        for ev in self.evidence:
            if ev.node_id == drop_id:
                ev.node_id = keep_id
        for e in self.edges:
            if e.source_id == drop_id:
                e.source_id = keep_id
            if e.target_id == drop_id:
                e.target_id = keep_id
        self.edges = [e for e in self.edges
                      if not (e.learner_id == learner_id and e.source_id == e.target_id)]
        best: dict[frozenset, Edge] = {}
        rest: list[Edge] = []
        dropped_bits: list[str] = []
        for e in self.edges:
            if e.learner_id != learner_id:
                rest.append(e)
                continue
            if keep_id not in (e.source_id, e.target_id):
                rest.append(e)
                continue
            key = frozenset((e.source_id, e.target_id))
            cur = best.get(key)
            e_key = (edge_rank(e.type), e.weight, e.id or "")
            if cur is None:
                best[key] = e
            else:
                c_key = (edge_rank(cur.type), cur.weight, cur.id or "")
                if e_key > c_key:
                    dropped_bits.append(f"{cur.type.value}@{cur.weight:.2f}")
                    best[key] = e
                else:
                    dropped_bits.append(f"{e.type.value}@{e.weight:.2f}")
        self.edges = rest + list(best.values())
        keep = self.nodes[keep_id]
        keep.mastery, keep.confidence = mastery, confidence
        keep.salience, keep.importance = salience, importance
        self.nodes[drop_id].forgotten_at = datetime.now(timezone.utc)
        audit = rationale
        if dropped_bits:
            audit = f"{rationale}; dropped duplicate edges: {', '.join(dropped_bits)}"
        self._audit_seq += 1
        self._audit_rows.append({
            "id": str(self._audit_seq), "learner_id": learner_id, "op": "merge",
            "rationale": audit, "model": None, "tokens": None, "cost": None,
            "ts": _AUDIT_BASE + timedelta(microseconds=self._audit_seq),
        })

    async def get_audit(self, learner_id: str, since=None, limit: int = 100) -> list[dict]:
        rows = [
            r
            for r in self._audit_rows
            if r["learner_id"] == learner_id and (since is None or r["ts"] > since)
        ]
        rows.sort(key=lambda r: r["ts"])
        keys = ("id", "op", "rationale", "model", "tokens", "cost", "ts")
        return [{k: r[k] for k in keys} for r in rows[:limit]]

    # --- voice sessions (host-layer) -------------------------------------

    async def create_voice_session(self, learner_id: str) -> str:
        sid = self._next_id()
        self.voice_sessions[sid] = {
            "id": sid, "learner_id": learner_id,
            "started_at": datetime.now(timezone.utc), "ended_at": None,
        }
        return sid

    async def end_voice_session(self, session_id: str) -> None:
        s = self.voice_sessions.get(session_id)
        if s is not None:
            s["ended_at"] = datetime.now(timezone.utc)

    async def append_voice_turn(self, session_id, learner_id, role, text) -> str:
        tid = self._next_id()
        self.voice_turns.append({
            "id": tid, "session_id": session_id, "learner_id": learner_id,
            "role": role, "text": text, "ts": datetime.now(timezone.utc),
        })
        return tid

    async def list_voice_sessions(self, learner_id: str, limit: int = 50) -> list[dict]:
        rows = [s for s in self.voice_sessions.values() if s["learner_id"] == learner_id]
        rows.sort(key=lambda s: s["started_at"], reverse=True)
        out = []
        for s in rows[:limit]:
            turns = sum(1 for t in self.voice_turns if t["session_id"] == s["id"])
            out.append({"id": s["id"], "started_at": s["started_at"],
                        "ended_at": s["ended_at"], "turns": turns})
        return out

    async def list_voice_turns(self, session_id: str) -> list[dict]:
        rows = [t for t in self.voice_turns if t["session_id"] == session_id]
        rows.sort(key=lambda t: t["ts"])
        return [{"id": t["id"], "role": t["role"], "text": t["text"], "ts": t["ts"]}
                for t in rows]
