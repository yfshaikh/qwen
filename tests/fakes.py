"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
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
from engram.core.recall import cosine_similarity

_cosine = cosine_similarity


_AUDIT_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
        self._mastery: list[dict] = []
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

    async def connect(self) -> None:
        pass  # in-memory: nothing to open

    async def close(self) -> None:
        pass  # in-memory: nothing to release

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
        self._mastery = [m for m in self._mastery if m["node_id"] not in dead]
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
        self, node_ids: list[str], per_node: int, *, with_embedding: bool = True
    ) -> dict[str, list[Evidence]]:
        out: dict[str, list[Evidence]] = {}
        for nid in node_ids:
            evs = [ev for ev in self.evidence if ev.node_id == nid]
            evs.sort(key=lambda e: (e.importance or 0.0), reverse=True)
            chosen = evs[:per_node]
            out[nid] = chosen if with_embedding else [replace(e, embedding=None) for e in chosen]
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

    async def get_live_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]:
        nodes = [
            n
            for n in self.nodes.values()
            if n.learner_id == learner_id and n.forgotten_at is None
        ]
        return nodes if with_embedding else [replace(n, embedding=None) for n in nodes]

    async def get_all_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]:
        nodes = [n for n in self.nodes.values() if n.learner_id == learner_id]
        return nodes if with_embedding else [replace(n, embedding=None) for n in nodes]

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
        idmap = self._insert_new_nodes(plan.new_nodes)

        def resolve_id(x: str) -> str:
            return idmap.get(x, x)

        self._apply_edge_updates(plan.new_edges, plan.edge_updates, resolve_id)
        self._insert_new_evidence(plan.new_evidence, resolve_id)
        self._apply_node_updates(plan.node_updates)
        self._append_mastery_history(plan.mastery_history, resolve_id)
        self._write_audit(plan.learner_id, plan.audit)
        self._stamp_events(plan.processed_event_ids)

    def _insert_new_nodes(self, new_nodes) -> dict[str, str]:
        """Insert brand-new nodes and return {temp_id: real_id} for resolve_id."""
        idmap: dict[str, str] = {}
        for n in new_nodes:
            temp = n.id
            n.id = self._next_id()
            idmap[temp] = n.id
            self.nodes[n.id] = n
        return idmap

    def _apply_edge_updates(self, new_edges, edge_updates, resolve_id) -> None:
        for e in new_edges:
            e.source_id = resolve_id(e.source_id)
            e.target_id = resolve_id(e.target_id)
            self._assert_unique_pair(e)
            e.id = e.id or self._next_id()
            self.edges.append(e)
        for upd in edge_updates:
            for e in self.edges:
                if e.id == upd.id:
                    e.type, e.weight = upd.type, upd.weight
                    e.source_id, e.target_id = upd.source_id, upd.target_id

    def _insert_new_evidence(self, new_evidence, resolve_id) -> None:
        for ev in new_evidence:
            ev.id = ev.id or self._next_id()
            ev.node_id = resolve_id(ev.node_id)
            self.evidence.append(ev)

    def _apply_node_updates(self, node_updates) -> None:
        for upd in node_updates:
            existing = self.nodes.get(upd.id)
            if existing is not None:
                existing.label = upd.label
                existing.mastery = upd.mastery
                existing.confidence = upd.confidence
                existing.salience = upd.salience
                existing.importance = upd.importance
                existing.last_seen_at = upd.last_seen_at
                existing.forgotten_at = upd.forgotten_at

    def _append_mastery_history(self, mastery_history, resolve_id) -> None:
        for mp in mastery_history:
            self._mastery.append({"node_id": resolve_id(mp.node_id), "mastery": mp.mastery,
                                  "confidence": mp.confidence,
                                  "ts": datetime.now(timezone.utc)})  # ponytail: wall-clock ts; tests that assert ordering seed _mastery directly

    def _write_audit(self, learner_id: str, audit) -> None:
        self.audit.extend(audit)
        for a in audit:
            self._audit_seq += 1
            self._audit_rows.append(
                {
                    "id": str(self._audit_seq),
                    "learner_id": learner_id,
                    "op": a.op,
                    "rationale": a.rationale,
                    "model": a.model,
                    "tokens": a.tokens,
                    "cost": a.cost,
                    "ts": _AUDIT_BASE + timedelta(microseconds=self._audit_seq),
                }
            )

    def _stamp_events(self, processed_event_ids) -> None:
        if processed_event_ids:
            stamp = datetime.now(timezone.utc)
            ids = set(processed_event_ids)
            for e in self.events:
                if e.id in ids:
                    e.consolidated_at = stamp

    async def apply_ontology(self, learner_id: str, nodes, edges) -> dict:
        """Mirrors PostgresStorage.apply_ontology exactly — see its docstring
        for the upsert contract. Ontology edges bypass insert_edge /
        _assert_unique_pair on purpose: ontology validation already
        guarantees one edge per undirected pair, and the wholesale delete
        below clears the old ones first."""
        ext_to_id = {
            n.external_id: nid
            for nid, n in self.nodes.items()
            if n.learner_id == learner_id and n.external_id is not None
        }
        inserted = updated = 0
        for n in nodes:
            existing = ext_to_id.get(n.external_id)
            if existing is not None:
                node = self.nodes[existing]
                node.label = n.label          # label/summary/embedding ONLY
                node.summary = n.summary
                node.embedding = n.embedding
                updated += 1
                continue
            n.id = self._next_id()
            self.nodes[n.id] = n
            ext_to_id[n.external_id] = n.id
            inserted += 1
        # Wholesale-replace edges among THIS ontology's concepts only — not
        # every ontology node the learner has, which would delete a
        # previously-seeded curriculum's edges.
        this_ids = {ext_to_id[n.external_id] for n in nodes}
        self.edges = [
            e for e in self.edges
            if not (e.learner_id == learner_id
                    and e.source_id in this_ids and e.target_id in this_ids)
        ]
        n_edges = 0
        for e in edges:
            s, t = ext_to_id.get(e.source_id), ext_to_id.get(e.target_id)
            if not s or not t:
                continue
            e.source_id, e.target_id = s, t
            e.id = self._next_id()
            self.edges.append(e)
            n_edges += 1
        return {"inserted": inserted, "updated": updated, "edges": n_edges}

    async def merge_nodes(self, learner_id, keep_id, drop_id, *, label, mastery,
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
        keep.label = label
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

    # --- insights read methods ---------------------------------------------

    async def mastery_history(self, learner_id, node_ids=None, since=None) -> list[dict]:
        mine = {nid for nid, n in self.nodes.items() if n.learner_id == learner_id}
        rows = [m for m in self._mastery if m["node_id"] in mine
                and (node_ids is None or m["node_id"] in node_ids)
                and (since is None or m["ts"] >= since)]
        return sorted(rows, key=lambda m: m["ts"])

    async def evidence_counts_by_kind(self, learner_id) -> list[dict]:
        node_learner = {nid: n.learner_id for nid, n in self.nodes.items()}
        counts: dict[tuple[str, str], int] = {}
        for ev in self.evidence:
            if node_learner.get(ev.node_id) != learner_id:
                continue
            counts[(ev.node_id, ev.kind.value)] = counts.get((ev.node_id, ev.kind.value), 0) + 1
        return [{"node_id": nid, "kind": k, "count": c} for (nid, k), c in counts.items()]

    async def last_event_at(self, learner_id: str) -> datetime | None:
        ts = [e.ts for e in self.events if e.learner_id == learner_id]
        return max(ts) if ts else None

    async def count_voice_sessions(self, learner_id: str) -> int:
        return sum(1 for s in self.voice_sessions.values() if s["learner_id"] == learner_id)

    async def event_counts_by_day(self, learner_id, days: int = 30) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        buckets: dict = {}
        for e in self.events:
            if e.learner_id != learner_id or e.ts < cutoff:
                continue
            buckets[e.ts.date()] = buckets.get(e.ts.date(), 0) + 1
        return [{"day": d, "count": c} for d, c in sorted(buckets.items())]
