"""Consolidation-path methods (Phase 2): pending-event reads, node snapshots,
the advisory lock, plan application, and node-merge repair.

`apply_consolidation` runs its seven helpers inside ONE `async with
conn.transaction()` — they all take `conn` as a parameter rather than
acquiring their own, so the whole plan commits or rolls back atomically.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg

from engram.core.edges import edge_rank_case_sql
from engram.core.models import LearningEvent, Node

from ._base import _EVENT_COLS, _NODE_COLS, _NODE_COLS_LITE, _Base, _row_to_event, _row_to_node

# merge_nodes collision predicate: a = the weaker edge of a keep-X / drop-X
# collision pair; shared by the audit SELECT and the DELETE so they can never
# disagree. The rank CASE is generated from engram.core.edges.EDGE_RANK (single
# source — B3) so it can never drift from edge_rank(), which FakeStorage uses.
_MERGE_COLLISION_SQL = f"""
    a.learner_id=$1 AND b.learner_id=$1 AND a.id <> b.id
    AND (a.source_id IN ($2,$3) OR a.target_id IN ($2,$3))
    AND (b.source_id IN ($2,$3) OR b.target_id IN ($2,$3))
    AND (CASE WHEN a.source_id IN ($2,$3) THEN a.target_id
              ELSE a.source_id END)
      = (CASE WHEN b.source_id IN ($2,$3) THEN b.target_id
              ELSE b.source_id END)
    AND ({edge_rank_case_sql("a.type")}, a.weight, a.id)
      < ({edge_rank_case_sql("b.type")}, b.weight, b.id)
"""


class _ConsolidationMixin(_Base):
    async def get_pending_events(
        self, learner_id: str, *, limit: int | None = None
    ) -> list[LearningEvent]:
        async with self._require_pool.acquire() as conn:
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
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_EVENT_COLS} FROM engram_events "
                "WHERE learner_id = $1 ORDER BY ts DESC LIMIT $2",
                learner_id,
                limit,
            )
            return [_row_to_event(r) for r in reversed(rows)]

    async def get_live_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]:
        cols = _NODE_COLS if with_embedding else _NODE_COLS_LITE
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {cols} FROM engram_nodes "
                "WHERE learner_id = $1 AND forgotten_at IS NULL",
                learner_id,
            )
            return [_row_to_node(r, with_embedding=with_embedding) for r in rows]

    async def get_all_nodes(
        self, learner_id: str, *, with_embedding: bool = True
    ) -> list[Node]:
        cols = _NODE_COLS if with_embedding else _NODE_COLS_LITE
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {cols} FROM engram_nodes WHERE learner_id = $1",
                learner_id,
            )
            return [_row_to_node(r, with_embedding=with_embedding) for r in rows]

    @asynccontextmanager
    async def consolidation_lock(self, learner_id: str):
        async with self._require_pool.acquire() as conn:
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
        async with self._require_pool.acquire() as conn:
            async with conn.transaction():
                idmap = await self._insert_new_nodes(conn, plan.new_nodes)

                def resolve_id(x: str) -> str:
                    return idmap.get(x, x)

                await self._apply_edge_updates(conn, plan.new_edges, plan.edge_updates, resolve_id)
                await self._insert_new_evidence(conn, plan.new_evidence, resolve_id)
                await self._apply_node_updates(conn, plan.node_updates)
                await self._append_mastery_history(conn, plan.mastery_history, resolve_id)
                await self._write_audit(conn, plan.learner_id, plan.audit)
                await self._stamp_events(conn, plan.processed_event_ids)

    async def _insert_new_nodes(self, conn: asyncpg.Connection, new_nodes) -> dict[str, str]:
        """Insert brand-new nodes and return {temp_id: real_id} for resolve_id."""
        idmap: dict[str, str] = {}
        for n in new_nodes:
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
        return idmap

    async def _apply_edge_updates(self, conn: asyncpg.Connection, new_edges, edge_updates,
                                  resolve_id) -> None:
        for e in new_edges:
            await conn.execute(
                "INSERT INTO engram_edges (learner_id, source_id, target_id, type, weight)"
                " VALUES ($1,$2,$3,$4,$5)",
                e.learner_id, resolve_id(e.source_id), resolve_id(e.target_id), e.type.value, e.weight,
            )
        for e in edge_updates:
            await conn.execute(
                "UPDATE engram_edges SET type=$1, weight=$2,"
                " source_id=$3, target_id=$4 WHERE id=$5",
                e.type.value, e.weight, e.source_id, e.target_id, e.id,
            )

    async def _insert_new_evidence(self, conn: asyncpg.Connection, new_evidence, resolve_id) -> None:
        for ev in new_evidence:
            await conn.execute(
                "INSERT INTO engram_evidence"
                " (node_id, kind, content, source_ref, embedding, importance)"
                " VALUES ($1,$2,$3,$4,$5,$6)",
                resolve_id(ev.node_id), ev.kind.value, ev.content, ev.source_ref,
                ev.embedding, ev.importance,
            )

    async def _apply_node_updates(self, conn: asyncpg.Connection, node_updates) -> None:
        for n in node_updates:
            await conn.execute(
                "UPDATE engram_nodes SET label=$1, mastery=$2, confidence=$3,"
                " salience=$4, importance=$5, last_seen_at=$6, forgotten_at=$7"
                " WHERE id=$8",
                n.label, n.mastery, n.confidence, n.salience, n.importance,
                n.last_seen_at, n.forgotten_at, n.id,
            )

    async def _append_mastery_history(self, conn: asyncpg.Connection, mastery_history,
                                      resolve_id) -> None:
        for mp in mastery_history:
            await conn.execute(
                "INSERT INTO engram_mastery_history (node_id, mastery, confidence)"
                " VALUES ($1,$2,$3)",
                resolve_id(mp.node_id), mp.mastery, mp.confidence,
            )

    async def _write_audit(self, conn: asyncpg.Connection, learner_id: str, audit) -> None:
        for a in audit:
            await conn.execute(
                "INSERT INTO engram_audit"
                " (learner_id, op, input_refs, output_refs, rationale, model, tokens, cost)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                learner_id, a.op, a.input_refs, a.output_refs,
                a.rationale, a.model, a.tokens, a.cost,
            )

    async def _stamp_events(self, conn: asyncpg.Connection, processed_event_ids) -> None:
        if processed_event_ids:
            await conn.execute(
                "UPDATE engram_events SET consolidated_at = now()"
                " WHERE id = ANY($1::uuid[])",
                processed_event_ids,
            )

    async def merge_nodes(self, learner_id: str, keep_id: str, drop_id: str, *,
                          label, mastery, confidence, salience, importance,
                          rationale: str) -> None:
        """Repair-merge drop into keep: union evidence, resolve edge collisions,
        repoint drop's edges, update keep's scores, soft-forget drop. One
        transaction; audited as op=merge with dropped duplicates itemized.

        Collision resolution runs BEFORE the repoint so the undirected-pair
        unique index (migration 0004) is never transiently violated. Tie-break
        matches FakeStorage: higher (edge_rank, weight, id) wins. The rank CASE
        in _MERGE_COLLISION_SQL is generated from engram.core.edges.EDGE_RANK.
        """
        async with self._require_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE engram_evidence SET node_id=$1 WHERE node_id=$2",
                    keep_id, drop_id)
                # 1. edges directly between keep and drop would become self-loops
                await conn.execute(
                    """
                    DELETE FROM engram_edges
                    WHERE learner_id=$1
                      AND ((source_id=$2 AND target_id=$3)
                        OR (source_id=$3 AND target_id=$2))
                    """,
                    learner_id, keep_id, drop_id)
                # 2. keep-X vs drop-X collisions: capture, then delete the weaker
                dropped = await conn.fetch(
                    f"SELECT a.type, a.weight FROM engram_edges a, engram_edges b"
                    f" WHERE {_MERGE_COLLISION_SQL}",
                    learner_id, keep_id, drop_id)
                await conn.execute(
                    f"DELETE FROM engram_edges a USING engram_edges b"
                    f" WHERE {_MERGE_COLLISION_SQL}",
                    learner_id, keep_id, drop_id)
                # 3. repoint what remains (collision-free by construction)
                await conn.execute(
                    "UPDATE engram_edges SET source_id=$1 WHERE source_id=$2",
                    keep_id, drop_id)
                await conn.execute(
                    "UPDATE engram_edges SET target_id=$1 WHERE target_id=$2",
                    keep_id, drop_id)
                await conn.execute(
                    "UPDATE engram_nodes SET label=$1, mastery=$2, confidence=$3,"
                    " salience=$4, importance=$5 WHERE id=$6",
                    label, mastery, confidence, salience, importance, keep_id)
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
        async with self._require_pool.acquire() as conn:
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
