"""Shared plumbing for the `postgres` package's mixins.

Holds the connection pool lifecycle (`connect`/`close`/`health`), the
`_require_pool` accessor every mixin method uses to reach the pool, and the
row->model converters (`_row_to_node`, `_row_to_event`, `_vec_to_list`) plus
the SQL column-list constants shared across writes/reads/consolidation.

Each pooled connection registers the pgvector codec (so embeddings pass as lists)
and a jsonb codec (so refs/signals/source_refs round-trip as Python objects).
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from engram.core.models import LearningEvent, Node, NodeType

_NODE_COLS = (
    "id, learner_id, type, label, summary, mastery, confidence, salience, "
    "importance, embedding, source_refs, forgotten_at, created_at, last_seen_at, "
    "external_id"
)
# Embedding-free projection for read paths that never touch node.embedding
# (insights, graph.build_graph) — cuts a ~1024-float column off the wire.
_NODE_COLS_LITE = (
    "id, learner_id, type, label, summary, mastery, confidence, salience, "
    "importance, source_refs, forgotten_at, created_at, last_seen_at, external_id"
)

_EVENT_COLS = "id, learner_id, type, text, refs, signals, ts, consolidated_at"


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def _row_to_event(row: asyncpg.Record) -> LearningEvent:
    return LearningEvent(
        id=str(row["id"]),
        learner_id=row["learner_id"],
        type=row["type"],
        text=row["text"],
        refs=row["refs"] if row["refs"] is not None else {},
        signals=row["signals"] if row["signals"] is not None else {},
        ts=row["ts"],
        consolidated_at=row["consolidated_at"],
    )


def _vec_to_list(emb: Any) -> list[float] | None:
    """pgvector <0.5 decodes to an iterable (list/ndarray of float32); >=0.5
    returns a Vector object. Coerce both to plain list[float] so the domain
    (and JSON serialization on the /recall path) sees list[float]."""
    if emb is None:
        return None
    if hasattr(emb, "to_list"):
        return [float(x) for x in emb.to_list()]
    return [float(x) for x in emb]


def _row_to_node(row: asyncpg.Record, *, with_embedding: bool = True) -> Node:
    emb = row["embedding"] if with_embedding else None
    return Node(
        id=str(row["id"]),
        learner_id=row["learner_id"],
        type=NodeType(row["type"]),
        label=row["label"],
        summary=row["summary"],
        mastery=row["mastery"],
        confidence=row["confidence"],
        salience=row["salience"],
        importance=row["importance"],
        embedding=_vec_to_list(emb),
        source_refs=row["source_refs"] if row["source_refs"] is not None else [],
        forgotten_at=row["forgotten_at"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        external_id=row["external_id"],
    )


class _Base:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=10, init=_init_conn
        )

    @property
    def _require_pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "PostgresStorage used before connect()"
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._require_pool.acquire() as conn:
                if await conn.fetchval("SELECT 1") != 1:
                    return False
                return bool(
                    await conn.fetchval(
                        "SELECT to_regclass('public.engram_nodes') IS NOT NULL"
                    )
                )
        except Exception:
            return False
