"""asyncpg-backed StoragePort with pgvector. Phase 1: full ingest + recall reads.

Each pooled connection registers the pgvector codec (so embeddings pass as lists)
and a jsonb codec (so refs/signals/source_refs round-trip as Python objects).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

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
    "importance, embedding, source_refs, forgotten_at, created_at, last_seen_at"
)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


_EVENT_COLS = "id, learner_id, type, text, refs, signals, ts, consolidated_at"


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
        importance=row["importance"],
        # pgvector yields numpy.float32 elements; coerce to plain float so the
        # domain (and JSON serialization on the /recall path) sees list[float].
        embedding=[float(x) for x in emb] if emb is not None else None,
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
                   salience, importance, embedding, source_refs, forgotten_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                RETURNING id
                """,
                n.learner_id, n.type.value, n.label, n.summary, n.mastery,
                n.confidence, n.salience, n.importance, n.embedding, n.source_refs, n.forgotten_at,
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

    async def delete_learner(self, learner_id: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # nodes cascade to edges/evidence/mastery_history (FK ON DELETE CASCADE)
                await conn.execute("DELETE FROM engram_nodes WHERE learner_id = $1", learner_id)
                await conn.execute("DELETE FROM engram_events WHERE learner_id = $1", learner_id)
                await conn.execute("DELETE FROM engram_audit WHERE learner_id = $1", learner_id)
                await conn.execute(
                    "DELETE FROM engram_voice_sessions WHERE learner_id = $1", learner_id
                )

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

    # --- consolidation (Phase 2) ----------------------------------------

    async def get_pending_events(
        self, learner_id: str, *, limit: int | None = None
    ) -> list[LearningEvent]:
        async with self._pool.acquire() as conn:
            if limit is None:
                rows = await conn.fetch(
                    f"SELECT {_EVENT_COLS} FROM engram_events "
                    "WHERE learner_id = $1 AND consolidated_at IS NULL ORDER BY ts",
                    learner_id,
                )
            else:
                # Newest-first fetch, then chronological for the buffer.
                rows = await conn.fetch(
                    f"SELECT {_EVENT_COLS} FROM engram_events "
                    "WHERE learner_id = $1 AND consolidated_at IS NULL "
                    "ORDER BY ts DESC LIMIT $2",
                    learner_id, limit,
                )
                rows = list(reversed(rows))
            return [_row_to_event(r) for r in rows]

    async def get_events(
        self, learner_id: str, limit: int = 200
    ) -> list[LearningEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_EVENT_COLS} FROM engram_events "
                "WHERE learner_id = $1 ORDER BY ts DESC LIMIT $2",
                learner_id,
                limit,
            )
            return [_row_to_event(r) for r in reversed(rows)]

    async def get_live_nodes(self, learner_id: str) -> list[Node]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_NODE_COLS} FROM engram_nodes "
                "WHERE learner_id = $1 AND forgotten_at IS NULL",
                learner_id,
            )
            return [_row_to_node(r) for r in rows]

    async def get_all_nodes(self, learner_id: str) -> list[Node]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_NODE_COLS} FROM engram_nodes WHERE learner_id = $1",
                learner_id,
            )
            return [_row_to_node(r) for r in rows]

    @asynccontextmanager
    async def consolidation_lock(self, learner_id: str):
        async with self._pool.acquire() as conn:
            got = await conn.fetchval(
                "SELECT pg_try_advisory_lock(hashtext($1))", learner_id
            )
            try:
                yield bool(got)
            finally:
                if got:
                    await conn.fetchval(
                        "SELECT pg_advisory_unlock(hashtext($1))", learner_id
                    )

    async def apply_consolidation(self, plan) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                idmap: dict[str, str] = {}
                for n in plan.new_nodes:
                    real = await conn.fetchval(
                        """
                        INSERT INTO engram_nodes
                          (learner_id, type, label, summary, mastery, confidence,
                           salience, importance, embedding, source_refs, forgotten_at, last_seen_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        RETURNING id
                        """,
                        n.learner_id, n.type.value, n.label, n.summary, n.mastery,
                        n.confidence, n.salience, n.importance, n.embedding, n.source_refs,
                        n.forgotten_at, n.last_seen_at,
                    )
                    idmap[n.id] = str(real)

                def rid(x: str) -> str:
                    return idmap.get(x, x)

                for e in plan.new_edges:
                    await conn.execute(
                        "INSERT INTO engram_edges (learner_id, source_id, target_id, type, weight)"
                        " VALUES ($1,$2,$3,$4,$5)",
                        e.learner_id, rid(e.source_id), rid(e.target_id), e.type.value, e.weight,
                    )
                for e in plan.edge_updates:
                    await conn.execute(
                        "UPDATE engram_edges SET type=$1, weight=$2,"
                        " source_id=$3, target_id=$4 WHERE id=$5",
                        e.type.value, e.weight, e.source_id, e.target_id, e.id,
                    )
                for ev in plan.new_evidence:
                    await conn.execute(
                        "INSERT INTO engram_evidence"
                        " (node_id, kind, content, source_ref, embedding, importance)"
                        " VALUES ($1,$2,$3,$4,$5,$6)",
                        rid(ev.node_id), ev.kind.value, ev.content, ev.source_ref,
                        ev.embedding, ev.importance,
                    )
                for n in plan.node_updates:
                    await conn.execute(
                        "UPDATE engram_nodes SET mastery=$1, confidence=$2, salience=$3,"
                        " importance=$4, last_seen_at=$5, forgotten_at=$6 WHERE id=$7",
                        n.mastery, n.confidence, n.salience, n.importance,
                        n.last_seen_at, n.forgotten_at, n.id,
                    )
                for mp in plan.mastery_history:
                    await conn.execute(
                        "INSERT INTO engram_mastery_history (node_id, mastery, confidence)"
                        " VALUES ($1,$2,$3)",
                        rid(mp.node_id), mp.mastery, mp.confidence,
                    )
                for a in plan.audit:
                    await conn.execute(
                        "INSERT INTO engram_audit"
                        " (learner_id, op, input_refs, output_refs, rationale, model, tokens, cost)"
                        " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                        plan.learner_id, a.op, a.input_refs, a.output_refs,
                        a.rationale, a.model, a.tokens, a.cost,
                    )
                if plan.processed_event_ids:
                    await conn.execute(
                        "UPDATE engram_events SET consolidated_at = now()"
                        " WHERE id = ANY($1::uuid[])",
                        plan.processed_event_ids,
                    )

    async def merge_nodes(self, learner_id: str, keep_id: str, drop_id: str, *,
                          mastery, confidence, salience, importance,
                          rationale: str) -> None:
        """Repair-merge drop into keep: union evidence, repoint edges (dropping
        self-loops and weaker duplicates on keep's incident pairs), update keep's
        scores, soft-forget drop. One transaction; audited as op=merge.

        Duplicate-edge cleanup is scoped to pairs touching keep_id (not
        learner-wide). Tie-break matches FakeStorage: higher
        (edge_rank, weight, id) wins. Rank CASE must stay in sync with
        engram.core.edges.EDGE_RANK.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE engram_evidence SET node_id=$1 WHERE node_id=$2",
                    keep_id, drop_id)
                await conn.execute(
                    "UPDATE engram_edges SET source_id=$1 WHERE source_id=$2",
                    keep_id, drop_id)
                await conn.execute(
                    "UPDATE engram_edges SET target_id=$1 WHERE target_id=$2",
                    keep_id, drop_id)
                await conn.execute(
                    "DELETE FROM engram_edges WHERE learner_id=$1 AND source_id=target_id",
                    learner_id)
                # Capture weaker duplicates before delete for the audit trail.
                dropped = await conn.fetch(
                    """
                    SELECT a.id, a.type, a.weight, a.source_id, a.target_id
                    FROM engram_edges a
                    JOIN engram_edges b ON a.learner_id=b.learner_id AND a.id <> b.id
                      AND ((a.source_id=b.source_id AND a.target_id=b.target_id)
                        OR (a.source_id=b.target_id AND a.target_id=b.source_id))
                      AND (a.source_id=$2 OR a.target_id=$2)
                      AND (b.source_id=$2 OR b.target_id=$2)
                      AND (CASE a.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
                           a.weight, a.id)
                        < (CASE b.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
                           b.weight, b.id)
                    WHERE a.learner_id=$1
                    """,
                    learner_id, keep_id)
                await conn.execute(
                    """
                    DELETE FROM engram_edges a USING engram_edges b
                    WHERE a.learner_id=$1 AND b.learner_id=$1 AND a.id <> b.id
                      AND (a.source_id=$2 OR a.target_id=$2)
                      AND (b.source_id=$2 OR b.target_id=$2)
                      AND ((a.source_id=b.source_id AND a.target_id=b.target_id)
                        OR (a.source_id=b.target_id AND a.target_id=b.source_id))
                      AND (CASE a.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
                           a.weight, a.id)
                        < (CASE b.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
                           b.weight, b.id)
                    """,
                    learner_id, keep_id)
                await conn.execute(
                    "UPDATE engram_nodes SET mastery=$1, confidence=$2, salience=$3,"
                    " importance=$4 WHERE id=$5",
                    mastery, confidence, salience, importance, keep_id)
                await conn.execute(
                    "UPDATE engram_nodes SET forgotten_at=now() WHERE id=$1", drop_id)
                audit = rationale
                if dropped:
                    bits = ", ".join(
                        f"{r['type']}@{float(r['weight']):.2f}" for r in dropped)
                    audit = f"{rationale}; dropped duplicate edges: {bits}"
                await conn.execute(
                    "INSERT INTO engram_audit (learner_id, op, rationale)"
                    " VALUES ($1, 'merge', $2)",
                    learner_id, audit)

    async def get_audit(self, learner_id: str, since=None, limit: int = 100) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, op, rationale, model, tokens, cost, ts FROM engram_audit "
                "WHERE learner_id = $1 AND ($2::timestamptz IS NULL OR ts > $2) "
                "ORDER BY ts LIMIT $3",
                learner_id, since, limit,
            )
            return [
                {
                    "id": str(r["id"]),
                    "op": r["op"],
                    "rationale": r["rationale"],
                    "model": r["model"],
                    "tokens": r["tokens"],
                    "cost": float(r["cost"]) if r["cost"] is not None else None,
                    "ts": r["ts"],
                }
                for r in rows
            ]

    # --- voice sessions (host-layer) ------------------------------------

    async def create_voice_session(self, learner_id: str) -> str:
        async with self._pool.acquire() as conn:
            sid = await conn.fetchval(
                "INSERT INTO engram_voice_sessions (learner_id) VALUES ($1) RETURNING id",
                learner_id,
            )
            return str(sid)

    async def end_voice_session(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE engram_voice_sessions SET ended_at = now() WHERE id = $1",
                session_id,
            )

    async def append_voice_turn(self, session_id, learner_id, role, text) -> str:
        async with self._pool.acquire() as conn:
            tid = await conn.fetchval(
                "INSERT INTO engram_voice_turns (session_id, learner_id, role, text)"
                " VALUES ($1,$2,$3,$4) RETURNING id",
                session_id, learner_id, role, text,
            )
            return str(tid)

    async def list_voice_sessions(self, learner_id: str, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.id, s.started_at, s.ended_at,
                       count(t.id) AS turns
                FROM engram_voice_sessions s
                LEFT JOIN engram_voice_turns t ON t.session_id = s.id
                WHERE s.learner_id = $1
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT $2
                """,
                learner_id, limit,
            )
            return [{"id": str(r["id"]), "started_at": r["started_at"],
                     "ended_at": r["ended_at"], "turns": r["turns"]} for r in rows]

    async def list_voice_turns(self, session_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, role, text, ts FROM engram_voice_turns"
                " WHERE session_id = $1 ORDER BY ts",
                session_id,
            )
            return [{"id": str(r["id"]), "role": r["role"], "text": r["text"],
                     "ts": r["ts"]} for r in rows]
