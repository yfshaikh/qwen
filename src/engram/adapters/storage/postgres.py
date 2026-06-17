"""asyncpg-backed StoragePort with pgvector. Phase 1: full ingest + recall reads.

Each pooled connection registers the pgvector codec (so embeddings pass as lists)
and a jsonb codec (so refs/signals/source_refs round-trip as Python objects).
"""

from __future__ import annotations

import json

import asyncpg
from pgvector.asyncpg import register_vector

from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)

_NODE_COLS = (
    "id, learner_id, type, label, summary, mastery, confidence, salience, "
    "embedding, source_refs, forgotten_at, created_at, last_seen_at"
)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def _row_to_node(row: asyncpg.Record) -> Node:
    emb = row["embedding"]
    return Node(
        id=str(row["id"]),
        learner_id=row["learner_id"],
        type=NodeType(row["type"]),
        label=row["label"],
        summary=row["summary"],
        mastery=row["mastery"],
        confidence=row["confidence"],
        salience=row["salience"],
        embedding=list(emb) if emb is not None else None,
        source_refs=row["source_refs"] if row["source_refs"] is not None else [],
        forgotten_at=row["forgotten_at"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


class PostgresStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=4, init=_init_conn
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
                if await conn.fetchval("SELECT 1") != 1:
                    return False
                return bool(
                    await conn.fetchval(
                        "SELECT to_regclass('public.engram_nodes') IS NOT NULL"
                    )
                )
        except Exception:
            return False

    # --- writes ---------------------------------------------------------

    async def insert_event(self, e: LearningEvent) -> str:
        async with self._pool.acquire() as conn:
            return str(await self._insert_event(conn, e))

    async def insert_events(self, events: list[LearningEvent]) -> list[str]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                return [str(await self._insert_event(conn, e)) for e in events]

    @staticmethod
    async def _insert_event(conn: asyncpg.Connection, e: LearningEvent):
        return await conn.fetchval(
            """
            INSERT INTO engram_events
              (learner_id, type, text, refs, signals, ts, consolidated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NULL)
            RETURNING id
            """,
            e.learner_id, e.type, e.text, e.refs, e.signals, e.ts,
        )

    async def insert_node(self, n: Node) -> str:
        async with self._pool.acquire() as conn:
            nid = await conn.fetchval(
                """
                INSERT INTO engram_nodes
                  (learner_id, type, label, summary, mastery, confidence,
                   salience, embedding, source_refs, forgotten_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                RETURNING id
                """,
                n.learner_id, n.type.value, n.label, n.summary, n.mastery,
                n.confidence, n.salience, n.embedding, n.source_refs, n.forgotten_at,
            )
            return str(nid)

    async def insert_edge(self, e: Edge) -> str:
        async with self._pool.acquire() as conn:
            eid = await conn.fetchval(
                """
                INSERT INTO engram_edges
                  (learner_id, source_id, target_id, type, weight)
                VALUES ($1,$2,$3,$4,$5)
                RETURNING id
                """,
                e.learner_id, e.source_id, e.target_id, e.type.value, e.weight,
            )
            return str(eid)

    async def insert_evidence(self, ev: Evidence) -> str:
        async with self._pool.acquire() as conn:
            evid = await conn.fetchval(
                """
                INSERT INTO engram_evidence
                  (node_id, kind, content, source_ref, embedding, importance)
                VALUES ($1,$2,$3,$4,$5,$6)
                RETURNING id
                """,
                ev.node_id, ev.kind.value, ev.content, ev.source_ref,
                ev.embedding, ev.importance,
            )
            return str(evid)

    # --- reads ----------------------------------------------------------

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_NODE_COLS} FROM engram_nodes
                WHERE learner_id = $1 AND forgotten_at IS NULL
                ORDER BY embedding <=> $2
                LIMIT $3
                """,
                learner_id, query_vec, k,
            )
            return [_row_to_node(r) for r in rows]

    async def get_edges(self, learner_id: str, node_ids: list[str]) -> list[Edge]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, learner_id, source_id, target_id, type, weight, created_at
                FROM engram_edges
                WHERE learner_id = $1
                  AND (source_id = ANY($2::uuid[]) OR target_id = ANY($2::uuid[]))
                """,
                learner_id, node_ids,
            )
            return [
                Edge(
                    id=str(r["id"]),
                    learner_id=r["learner_id"],
                    source_id=str(r["source_id"]),
                    target_id=str(r["target_id"]),
                    type=EdgeType(r["type"]),
                    weight=r["weight"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    async def get_nodes(self, learner_id: str, node_ids: list[str]) -> list[Node]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_NODE_COLS} FROM engram_nodes
                WHERE learner_id = $1 AND id = ANY($2::uuid[]) AND forgotten_at IS NULL
                """,
                learner_id, node_ids,
            )
            return [_row_to_node(r) for r in rows]

    async def top_evidence(
        self, node_ids: list[str], per_node: int
    ) -> dict[str, list[Evidence]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, node_id, kind, content, source_ref, embedding,
                       importance, created_at
                FROM (
                  SELECT *, row_number() OVER (
                    PARTITION BY node_id
                    ORDER BY importance DESC NULLS LAST, created_at DESC
                  ) AS rn
                  FROM engram_evidence
                  WHERE node_id = ANY($1::uuid[])
                ) t
                WHERE rn <= $2
                """,
                node_ids, per_node,
            )
        out: dict[str, list[Evidence]] = {nid: [] for nid in node_ids}
        for r in rows:
            emb = r["embedding"]
            out.setdefault(str(r["node_id"]), []).append(
                Evidence(
                    id=str(r["id"]),
                    node_id=str(r["node_id"]),
                    kind=EvidenceKind(r["kind"]),
                    content=r["content"],
                    source_ref=r["source_ref"],
                    embedding=list(emb) if emb is not None else None,
                    importance=r["importance"],
                    created_at=r["created_at"],
                )
            )
        return out
