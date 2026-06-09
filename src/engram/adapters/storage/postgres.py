"""asyncpg + pgvector backed StoragePort.

A faithful twin of `InMemoryStorage` (see `memory.py`) backed by Postgres 16 +
pgvector. Same return types, ordering guarantees, and dedupe semantics — the two
implementations are interchangeable behind `StoragePort`.

Per-connection setup registers a pgvector codec (so `vector` columns round-trip
as plain Python lists) and a jsonb codec (so dicts/lists pass straight through).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg
from pgvector.asyncpg import register_vector

from engram.core.models import (
    AuditEntry,
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register vector + jsonb codecs on every pooled connection."""
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


def _row_to_event(row: asyncpg.Record) -> LearningEvent:
    return LearningEvent(
        learner_id=row["learner_id"],
        type=row["type"],
        text=row["text"],
        refs=row["refs"] or {},
        signals=row["signals"] or {},
        ts=row["ts"],
        id=str(row["id"]),
        consolidated_at=row["consolidated_at"],
    )


def _row_to_node(row: asyncpg.Record) -> Node:
    embedding = row["embedding"]
    return Node(
        learner_id=row["learner_id"],
        type=NodeType(row["type"]),
        label=row["label"],
        id=str(row["id"]),
        summary=row["summary"],
        mastery=row["mastery"],
        confidence=row["confidence"],
        salience=row["salience"],
        embedding=list(embedding) if embedding is not None else None,
        source_refs=row["source_refs"] or [],
        forgotten_at=row["forgotten_at"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


def _row_to_edge(row: asyncpg.Record) -> Edge:
    return Edge(
        learner_id=row["learner_id"],
        source_id=str(row["source_id"]),
        target_id=str(row["target_id"]),
        type=EdgeType(row["type"]),
        id=str(row["id"]),
        weight=row["weight"],
        created_at=row["created_at"],
    )


def _row_to_evidence(row: asyncpg.Record) -> Evidence:
    embedding = row["embedding"]
    return Evidence(
        node_id=str(row["node_id"]),
        kind=EvidenceKind(row["kind"]),
        id=str(row["id"]),
        content=row["content"],
        source_ref=row["source_ref"],
        embedding=list(embedding) if embedding is not None else None,
        importance=row["importance"],
        created_at=row["created_at"],
    )


def _row_to_audit(row: asyncpg.Record) -> AuditEntry:
    cost = row["cost"]
    return AuditEntry(
        learner_id=row["learner_id"],
        op=row["op"],
        id=str(row["id"]),
        input_refs=row["input_refs"],
        output_refs=row["output_refs"],
        rationale=row["rationale"],
        model=row["model"],
        tokens=row["tokens"],
        cost=float(cost) if cost is not None else None,
        ts=row["ts"],
    )


class PostgresStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        # Small pool — register vector + jsonb codecs on each connection.
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=1,
            max_size=4,
            init=_init_connection,
        )
        # Dedupe key for edges, mirroring InMemoryStorage's
        # (learner, source, target, type) semantics via ON CONFLICT.
        async with self._pool.acquire() as conn:
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS engram_edges_unique_lstt "
                "ON engram_edges (learner_id, source_id, target_id, type)"
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                # Cheap reachability probe + assert the schema is present.
                val = await conn.fetchval("SELECT 1")
                if val != 1:
                    return False
                exists = await conn.fetchval(
                    "SELECT to_regclass('public.engram_nodes') IS NOT NULL"
                )
                return bool(exists)
        except Exception:
            return False

    @property
    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresStorage is not connected; call connect() first")
        return self._pool

    # --- Events ---
    async def insert_event(self, e: LearningEvent) -> str:
        async with self._p.acquire() as conn:
            if e.id is not None:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_events "
                    "(id, learner_id, type, text, refs, signals, ts, consolidated_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                    e.id,
                    e.learner_id,
                    e.type,
                    e.text,
                    e.refs,
                    e.signals,
                    e.ts,
                    e.consolidated_at,
                )
            else:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_events "
                    "(learner_id, type, text, refs, signals, ts, consolidated_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                    e.learner_id,
                    e.type,
                    e.text,
                    e.refs,
                    e.signals,
                    e.ts,
                    e.consolidated_at,
                )
        return str(row_id)

    async def insert_events(self, events: list[LearningEvent]) -> list[str]:
        return [await self.insert_event(e) for e in events]

    async def fetch_unconsolidated_events(
        self, learner_id: str, limit: int = 1000
    ) -> list[LearningEvent]:
        rows = await self._p.fetch(
            "SELECT * FROM engram_events "
            "WHERE learner_id = $1 AND consolidated_at IS NULL "
            "ORDER BY ts ASC LIMIT $2",
            learner_id,
            limit,
        )
        return [_row_to_event(r) for r in rows]

    async def mark_events_consolidated(
        self, event_ids: list[str], ts: datetime | None = None
    ) -> None:
        if not event_ids:
            return
        await self._p.execute(
            "UPDATE engram_events SET consolidated_at = $2 WHERE id = ANY($1::uuid[])",
            event_ids,
            ts or _now(),
        )

    async def count_pending_events(self, learner_id: str) -> int:
        val = await self._p.fetchval(
            "SELECT count(*) FROM engram_events "
            "WHERE learner_id = $1 AND consolidated_at IS NULL",
            learner_id,
        )
        return int(val)

    async def learners_with_pending_events(self, quiet_for_seconds: int = 0) -> list[str]:
        if quiet_for_seconds > 0:
            rows = await self._p.fetch(
                "SELECT learner_id FROM engram_events "
                "WHERE consolidated_at IS NULL "
                "GROUP BY learner_id "
                "HAVING max(ts) <= now() - ($1 || ' seconds')::interval "
                "ORDER BY learner_id",
                str(quiet_for_seconds),
            )
        else:
            rows = await self._p.fetch(
                "SELECT learner_id FROM engram_events "
                "WHERE consolidated_at IS NULL "
                "GROUP BY learner_id "
                "ORDER BY learner_id"
            )
        return [r["learner_id"] for r in rows]

    # --- Nodes ---
    async def upsert_node(self, node: Node) -> str:
        async with self._p.acquire() as conn:
            if node.id is not None:
                exists = await conn.fetchval(
                    "SELECT 1 FROM engram_nodes WHERE id = $1", node.id
                )
                if exists:
                    await conn.execute(
                        "UPDATE engram_nodes SET "
                        "learner_id = $2, type = $3, label = $4, summary = $5, "
                        "mastery = $6, confidence = $7, salience = $8, embedding = $9, "
                        "source_refs = $10, forgotten_at = $11, created_at = $12, "
                        "last_seen_at = $13 "
                        "WHERE id = $1",
                        node.id,
                        node.learner_id,
                        node.type.value,
                        node.label,
                        node.summary,
                        node.mastery,
                        node.confidence,
                        node.salience,
                        node.embedding,
                        node.source_refs,
                        node.forgotten_at,
                        node.created_at,
                        node.last_seen_at,
                    )
                    return node.id
                row_id = await conn.fetchval(
                    "INSERT INTO engram_nodes "
                    "(id, learner_id, type, label, summary, mastery, confidence, "
                    "salience, embedding, source_refs, forgotten_at, created_at, "
                    "last_seen_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
                    "RETURNING id",
                    node.id,
                    node.learner_id,
                    node.type.value,
                    node.label,
                    node.summary,
                    node.mastery,
                    node.confidence,
                    node.salience,
                    node.embedding,
                    node.source_refs,
                    node.forgotten_at,
                    node.created_at,
                    node.last_seen_at,
                )
                return str(row_id)
            row_id = await conn.fetchval(
                "INSERT INTO engram_nodes "
                "(learner_id, type, label, summary, mastery, confidence, salience, "
                "embedding, source_refs, forgotten_at, created_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) "
                "RETURNING id",
                node.learner_id,
                node.type.value,
                node.label,
                node.summary,
                node.mastery,
                node.confidence,
                node.salience,
                node.embedding,
                node.source_refs,
                node.forgotten_at,
                node.created_at,
                node.last_seen_at,
            )
        return str(row_id)

    async def get_node(self, node_id: str) -> Node | None:
        row = await self._p.fetchrow(
            "SELECT * FROM engram_nodes WHERE id = $1", node_id
        )
        return _row_to_node(row) if row is not None else None

    async def get_nodes(
        self,
        learner_id: str,
        types: list[str] | None = None,
        include_forgotten: bool = False,
    ) -> list[Node]:
        clauses = ["learner_id = $1"]
        params: list[object] = [learner_id]
        if types is not None:
            params.append(types)
            clauses.append(f"type = ANY(${len(params)})")
        if not include_forgotten:
            clauses.append("forgotten_at IS NULL")
        sql = (
            "SELECT * FROM engram_nodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY salience DESC NULLS LAST"
        )
        rows = await self._p.fetch(sql, *params)
        return [_row_to_node(r) for r in rows]

    async def vector_search(
        self,
        learner_id: str,
        query_vec: list[float],
        k: int,
        types: list[str] | None = None,
    ) -> list[tuple[Node, float]]:
        clauses = ["learner_id = $1", "embedding IS NOT NULL", "forgotten_at IS NULL"]
        params: list[object] = [learner_id, query_vec]
        if types is not None:
            params.append(types)
            clauses.append(f"type = ANY(${len(params)})")
        params.append(k)
        sql = (
            "SELECT *, 1 - (embedding <=> $2) AS similarity FROM engram_nodes WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY embedding <=> $2 LIMIT ${len(params)}"
        )
        rows = await self._p.fetch(sql, *params)
        return [(_row_to_node(r), float(r["similarity"])) for r in rows]

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
        sets: list[str] = []
        params: list[object] = [node_id]
        for column, value in (
            ("mastery", mastery),
            ("confidence", confidence),
            ("salience", salience),
            ("last_seen_at", last_seen_at),
            ("forgotten_at", forgotten_at),
            ("summary", summary),
            ("embedding", list(embedding) if embedding is not None else None),
        ):
            if value is not None:
                params.append(value)
                sets.append(f"{column} = ${len(params)}")
        if not sets:
            return
        await self._p.execute(
            f"UPDATE engram_nodes SET {', '.join(sets)} WHERE id = $1", *params
        )

    async def delete_node(self, node_id: str) -> None:
        # FK ON DELETE CASCADE cleans edges/evidence/mastery_history.
        await self._p.execute("DELETE FROM engram_nodes WHERE id = $1", node_id)

    # --- Edges ---
    async def upsert_edge(self, edge: Edge) -> str:
        # Dedupe on (learner, source, target, type) via the unique index built in
        # connect(); on conflict, update weight and return the existing id.
        async with self._p.acquire() as conn:
            if edge.id is not None:
                existing = await conn.fetchval(
                    "SELECT id FROM engram_edges WHERE learner_id = $1 "
                    "AND source_id = $2 AND target_id = $3 AND type = $4",
                    edge.learner_id,
                    edge.source_id,
                    edge.target_id,
                    edge.type.value,
                )
                if existing is None:
                    row_id = await conn.fetchval(
                        "INSERT INTO engram_edges "
                        "(id, learner_id, source_id, target_id, type, weight, "
                        "created_at) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                        edge.id,
                        edge.learner_id,
                        edge.source_id,
                        edge.target_id,
                        edge.type.value,
                        edge.weight,
                        edge.created_at,
                    )
                    return str(row_id)
                await conn.execute(
                    "UPDATE engram_edges SET weight = $2 WHERE id = $1",
                    existing,
                    edge.weight,
                )
                return str(existing)
            row_id = await conn.fetchval(
                "INSERT INTO engram_edges "
                "(learner_id, source_id, target_id, type, weight, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (learner_id, source_id, target_id, type) "
                "DO UPDATE SET weight = EXCLUDED.weight "
                "RETURNING id",
                edge.learner_id,
                edge.source_id,
                edge.target_id,
                edge.type.value,
                edge.weight,
                edge.created_at,
            )
        return str(row_id)

    async def get_edges(
        self, learner_id: str, node_ids: list[str] | None = None
    ) -> list[Edge]:
        if node_ids is not None:
            rows = await self._p.fetch(
                "SELECT * FROM engram_edges WHERE learner_id = $1 "
                "AND (source_id = ANY($2::uuid[]) OR target_id = ANY($2::uuid[]))",
                learner_id,
                node_ids,
            )
        else:
            rows = await self._p.fetch(
                "SELECT * FROM engram_edges WHERE learner_id = $1", learner_id
            )
        return [_row_to_edge(r) for r in rows]

    # --- Evidence ---
    async def insert_evidence(self, ev: Evidence) -> str:
        async with self._p.acquire() as conn:
            if ev.id is not None:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_evidence "
                    "(id, node_id, kind, content, source_ref, embedding, importance, "
                    "created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                    ev.id,
                    ev.node_id,
                    ev.kind.value,
                    ev.content,
                    ev.source_ref,
                    ev.embedding,
                    ev.importance,
                    ev.created_at,
                )
            else:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_evidence "
                    "(node_id, kind, content, source_ref, embedding, importance, "
                    "created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                    ev.node_id,
                    ev.kind.value,
                    ev.content,
                    ev.source_ref,
                    ev.embedding,
                    ev.importance,
                    ev.created_at,
                )
        return str(row_id)

    async def get_evidence(self, node_id: str, limit: int = 50) -> list[Evidence]:
        rows = await self._p.fetch(
            "SELECT * FROM engram_evidence WHERE node_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            node_id,
            limit,
        )
        return [_row_to_evidence(r) for r in rows]

    async def evidence_counts(self, node_ids: list[str]) -> dict[str, int]:
        counts = {nid: 0 for nid in node_ids}
        if not node_ids:
            return counts
        rows = await self._p.fetch(
            "SELECT node_id, count(*) AS n FROM engram_evidence "
            "WHERE node_id = ANY($1::uuid[]) GROUP BY node_id",
            node_ids,
        )
        for r in rows:
            counts[str(r["node_id"])] = int(r["n"])
        return counts

    # --- Audit + mastery history ---
    async def insert_audit(self, entry: AuditEntry) -> str:
        async with self._p.acquire() as conn:
            if entry.id is not None:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_audit "
                    "(id, learner_id, op, input_refs, output_refs, rationale, model, "
                    "tokens, cost, ts) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id",
                    entry.id,
                    entry.learner_id,
                    entry.op,
                    entry.input_refs,
                    entry.output_refs,
                    entry.rationale,
                    entry.model,
                    entry.tokens,
                    entry.cost,
                    entry.ts,
                )
            else:
                row_id = await conn.fetchval(
                    "INSERT INTO engram_audit "
                    "(learner_id, op, input_refs, output_refs, rationale, model, "
                    "tokens, cost, ts) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id",
                    entry.learner_id,
                    entry.op,
                    entry.input_refs,
                    entry.output_refs,
                    entry.rationale,
                    entry.model,
                    entry.tokens,
                    entry.cost,
                    entry.ts,
                )
        return str(row_id)

    async def get_audit(self, learner_id: str, limit: int = 100) -> list[AuditEntry]:
        rows = await self._p.fetch(
            "SELECT * FROM engram_audit WHERE learner_id = $1 "
            "ORDER BY ts DESC LIMIT $2",
            learner_id,
            limit,
        )
        return [_row_to_audit(r) for r in rows]

    async def insert_mastery_snapshot(
        self,
        node_id: str,
        mastery: float | None,
        confidence: float | None,
        ts: datetime | None = None,
    ) -> None:
        await self._p.execute(
            "INSERT INTO engram_mastery_history (node_id, mastery, confidence, ts) "
            "VALUES ($1, $2, $3, $4)",
            node_id,
            mastery,
            confidence,
            ts or _now(),
        )

    async def get_mastery_history(
        self, node_id: str
    ) -> list[tuple[datetime, float | None, float | None]]:
        rows = await self._p.fetch(
            "SELECT ts, mastery, confidence FROM engram_mastery_history "
            "WHERE node_id = $1 ORDER BY ts ASC",
            node_id,
        )
        return [(r["ts"], r["mastery"], r["confidence"]) for r in rows]
