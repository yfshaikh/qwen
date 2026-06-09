"""asyncpg-backed StoragePort.

Implements the full `StoragePort` contract against Postgres 16 + pgvector,
mirroring `InMemoryStorage` semantics (ordering, dedupe, return types).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

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


def _vec(value: Any) -> list[float] | None:
    """Convert a pgvector column value (ndarray or None) to a plain list."""
    if value is None:
        return None
    return [float(x) for x in value]


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def _event_from_row(row: asyncpg.Record) -> LearningEvent:
    return LearningEvent(
        learner_id=row["learner_id"],
        type=row["type"],
        text=row["text"],
        refs=row["refs"],
        signals=row["signals"],
        ts=row["ts"],
        id=str(row["id"]),
        consolidated_at=row["consolidated_at"],
    )


def _node_from_row(row: asyncpg.Record) -> Node:
    return Node(
        learner_id=row["learner_id"],
        type=NodeType(row["type"]),
        label=row["label"],
        id=str(row["id"]),
        summary=row["summary"],
        mastery=row["mastery"],
        confidence=row["confidence"],
        salience=row["salience"],
        embedding=_vec(row["embedding"]),
        source_refs=row["source_refs"],
        forgotten_at=row["forgotten_at"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


def _edge_from_row(row: asyncpg.Record) -> Edge:
    return Edge(
        learner_id=row["learner_id"],
        source_id=str(row["source_id"]),
        target_id=str(row["target_id"]),
        type=EdgeType(row["type"]),
        id=str(row["id"]),
        weight=row["weight"],
        created_at=row["created_at"],
    )


def _evidence_from_row(row: asyncpg.Record) -> Evidence:
    return Evidence(
        node_id=str(row["node_id"]),
        kind=EvidenceKind(row["kind"]),
        id=str(row["id"]),
        content=row["content"],
        source_ref=row["source_ref"],
        embedding=_vec(row["embedding"]),
        importance=row["importance"],
        created_at=row["created_at"],
    )


def _audit_from_row(row: asyncpg.Record) -> AuditEntry:
    return AuditEntry(
        learner_id=row["learner_id"],
        op=row["op"],
        id=str(row["id"]),
        input_refs=row["input_refs"],
        output_refs=row["output_refs"],
        rationale=row["rationale"],
        model=row["model"],
        tokens=row["tokens"],
        cost=float(row["cost"]) if row["cost"] is not None else None,
        ts=row["ts"],
    )


class PostgresStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        # Small pool — tune later if needed.
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=4, init=_init_connection
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS engram_edges_dedupe
                  ON engram_edges (learner_id, source_id, target_id, type)
                """
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

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresStorage is not connected; call connect() first")
        return self._pool

    # --- Events ---
    async def insert_event(self, e: LearningEvent) -> str:
        pool = self._require_pool()
        row_id = await pool.fetchval(
            """
            INSERT INTO engram_events (id, learner_id, type, text, refs, signals,
                                       ts, consolidated_at)
            VALUES (coalesce($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            e.id,
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
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM engram_events
            WHERE learner_id = $1 AND consolidated_at IS NULL
            ORDER BY ts ASC
            LIMIT $2
            """,
            learner_id,
            limit,
        )
        return [_event_from_row(r) for r in rows]

    async def mark_events_consolidated(
        self, event_ids: list[str], ts: datetime | None = None
    ) -> None:
        pool = self._require_pool()
        await pool.execute(
            "UPDATE engram_events SET consolidated_at = $2 WHERE id = ANY($1::uuid[])",
            event_ids,
            ts or _now(),
        )

    async def count_pending_events(self, learner_id: str) -> int:
        pool = self._require_pool()
        count = await pool.fetchval(
            """
            SELECT count(*) FROM engram_events
            WHERE learner_id = $1 AND consolidated_at IS NULL
            """,
            learner_id,
        )
        return int(count)

    async def learners_with_pending_events(self, quiet_for_seconds: int = 0) -> list[str]:
        # "Quiet" is judged on the learner's latest event overall (consolidated
        # or not), matching InMemoryStorage.
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT learner_id
            FROM engram_events
            GROUP BY learner_id
            HAVING bool_or(consolidated_at IS NULL)
               AND ($1::int <= 0 OR max(ts) <= now() - make_interval(secs => $1::int))
            ORDER BY learner_id
            """,
            quiet_for_seconds,
        )
        return [r["learner_id"] for r in rows]

    # --- Nodes ---
    async def upsert_node(self, node: Node) -> str:
        pool = self._require_pool()
        if node.id is not None:
            updated = await pool.fetchval(
                """
                UPDATE engram_nodes
                SET learner_id = $2, type = $3, label = $4, summary = $5, mastery = $6,
                    confidence = $7, salience = $8, embedding = $9, source_refs = $10,
                    forgotten_at = $11, created_at = $12, last_seen_at = $13
                WHERE id = $1::uuid
                RETURNING id
                """,
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
            if updated is not None:
                return str(updated)
        row_id = await pool.fetchval(
            """
            INSERT INTO engram_nodes (id, learner_id, type, label, summary, mastery,
                                      confidence, salience, embedding, source_refs,
                                      forgotten_at, created_at, last_seen_at)
            VALUES (coalesce($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13)
            RETURNING id
            """,
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

    async def get_node(self, node_id: str) -> Node | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            "SELECT * FROM engram_nodes WHERE id = $1::uuid", node_id
        )
        return _node_from_row(row) if row else None

    async def get_nodes(
        self,
        learner_id: str,
        types: list[str] | None = None,
        include_forgotten: bool = False,
    ) -> list[Node]:
        pool = self._require_pool()
        sql = "SELECT * FROM engram_nodes WHERE learner_id = $1"
        args: list[Any] = [learner_id]
        if types is not None:
            args.append(types)
            sql += f" AND type = ANY(${len(args)}::text[])"
        if not include_forgotten:
            sql += " AND forgotten_at IS NULL"
        sql += " ORDER BY salience DESC NULLS LAST"
        rows = await pool.fetch(sql, *args)
        return [_node_from_row(r) for r in rows]

    async def vector_search(
        self,
        learner_id: str,
        query_vec: list[float],
        k: int,
        types: list[str] | None = None,
    ) -> list[tuple[Node, float]]:
        pool = self._require_pool()
        sql = """
            SELECT *, (embedding <=> $2) AS distance
            FROM engram_nodes
            WHERE learner_id = $1 AND embedding IS NOT NULL AND forgotten_at IS NULL
        """
        args: list[Any] = [learner_id, query_vec]
        if types is not None:
            args.append(types)
            sql += f" AND type = ANY(${len(args)}::text[])"
        args.append(k)
        sql += f" ORDER BY embedding <=> $2 LIMIT ${len(args)}"
        rows = await pool.fetch(sql, *args)
        return [(_node_from_row(r), 1.0 - float(r["distance"])) for r in rows]

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
        fields: dict[str, Any] = {
            "mastery": mastery,
            "confidence": confidence,
            "salience": salience,
            "last_seen_at": last_seen_at,
            "forgotten_at": forgotten_at,
            "summary": summary,
            "embedding": embedding,
        }
        provided = {k: v for k, v in fields.items() if v is not None}
        if not provided:
            return
        sets, args = [], []
        for i, (col, val) in enumerate(provided.items(), start=2):
            sets.append(f"{col} = ${i}")
            args.append(val)
        pool = self._require_pool()
        await pool.execute(
            f"UPDATE engram_nodes SET {', '.join(sets)} WHERE id = $1::uuid",
            node_id,
            *args,
        )

    async def delete_node(self, node_id: str) -> None:
        # FK ON DELETE CASCADE cleans edges/evidence/mastery_history.
        pool = self._require_pool()
        await pool.execute("DELETE FROM engram_nodes WHERE id = $1::uuid", node_id)

    # --- Edges ---
    async def upsert_edge(self, edge: Edge) -> str:
        pool = self._require_pool()
        row_id = await pool.fetchval(
            """
            INSERT INTO engram_edges (learner_id, source_id, target_id, type,
                                      weight, created_at)
            VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6)
            ON CONFLICT (learner_id, source_id, target_id, type)
            DO UPDATE SET weight = EXCLUDED.weight
            RETURNING id
            """,
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
        pool = self._require_pool()
        if node_ids is None:
            rows = await pool.fetch(
                "SELECT * FROM engram_edges WHERE learner_id = $1", learner_id
            )
        else:
            rows = await pool.fetch(
                """
                SELECT * FROM engram_edges
                WHERE learner_id = $1
                  AND (source_id = ANY($2::uuid[]) OR target_id = ANY($2::uuid[]))
                """,
                learner_id,
                node_ids,
            )
        return [_edge_from_row(r) for r in rows]

    # --- Evidence ---
    async def insert_evidence(self, ev: Evidence) -> str:
        pool = self._require_pool()
        row_id = await pool.fetchval(
            """
            INSERT INTO engram_evidence (id, node_id, kind, content, source_ref,
                                         embedding, importance, created_at)
            VALUES (coalesce($1::uuid, gen_random_uuid()), $2::uuid, $3, $4, $5, $6,
                    $7, $8)
            RETURNING id
            """,
            ev.id,
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
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM engram_evidence
            WHERE node_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2
            """,
            node_id,
            limit,
        )
        return [_evidence_from_row(r) for r in rows]

    async def evidence_counts(self, node_ids: list[str]) -> dict[str, int]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT node_id, count(*) AS n
            FROM engram_evidence
            WHERE node_id = ANY($1::uuid[])
            GROUP BY node_id
            """,
            node_ids,
        )
        counts = {nid: 0 for nid in node_ids}
        for r in rows:
            counts[str(r["node_id"])] = int(r["n"])
        return counts

    # --- Audit + mastery history ---
    async def insert_audit(self, entry: AuditEntry) -> str:
        pool = self._require_pool()
        row_id = await pool.fetchval(
            """
            INSERT INTO engram_audit (id, learner_id, op, input_refs, output_refs,
                                      rationale, model, tokens, cost, ts)
            VALUES (coalesce($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8,
                    $9::float8, $10)
            RETURNING id
            """,
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
        return str(row_id)

    async def get_audit(self, learner_id: str, limit: int = 100) -> list[AuditEntry]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM engram_audit
            WHERE learner_id = $1
            ORDER BY ts DESC
            LIMIT $2
            """,
            learner_id,
            limit,
        )
        return [_audit_from_row(r) for r in rows]

    async def insert_mastery_snapshot(
        self,
        node_id: str,
        mastery: float | None,
        confidence: float | None,
        ts: datetime | None = None,
    ) -> None:
        pool = self._require_pool()
        await pool.execute(
            """
            INSERT INTO engram_mastery_history (node_id, mastery, confidence, ts)
            VALUES ($1::uuid, $2, $3, $4)
            """,
            node_id,
            mastery,
            confidence,
            ts or _now(),
        )

    async def get_mastery_history(
        self, node_id: str
    ) -> list[tuple[datetime, float | None, float | None]]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT ts, mastery, confidence FROM engram_mastery_history
            WHERE node_id = $1::uuid
            ORDER BY ts ASC
            """,
            node_id,
        )
        return [(r["ts"], r["mastery"], r["confidence"]) for r in rows]
