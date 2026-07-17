"""Write-path methods: event/node/edge/evidence ingest, learner deletion."""

from __future__ import annotations

import asyncpg

from engram.core.models import Edge, Evidence, LearningEvent, Node

from ._base import _Base


class _WritesMixin(_Base):
    async def insert_event(self, e: LearningEvent) -> str:
        async with self._require_pool.acquire() as conn:
            return str(await self._insert_event(conn, e))

    async def insert_events(self, events: list[LearningEvent]) -> list[str]:
        async with self._require_pool.acquire() as conn:
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
        async with self._require_pool.acquire() as conn:
            nid = await conn.fetchval(
                """
                INSERT INTO engram_nodes
                  (learner_id, type, label, summary, mastery, confidence,
                   salience, importance, embedding, source_refs, external_id,
                   forgotten_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING id
                """,
                n.learner_id, n.type.value, n.label, n.summary, n.mastery,
                n.confidence, n.salience, n.importance, n.embedding,
                n.source_refs, n.external_id, n.forgotten_at,
            )
            return str(nid)

    async def insert_edge(self, e: Edge) -> str:
        async with self._require_pool.acquire() as conn:
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
        async with self._require_pool.acquire() as conn:
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
        async with self._require_pool.acquire() as conn:
            async with conn.transaction():
                # nodes cascade to edges/evidence/mastery_history (FK ON DELETE CASCADE)
                await conn.execute("DELETE FROM engram_nodes WHERE learner_id = $1", learner_id)
                await conn.execute("DELETE FROM engram_events WHERE learner_id = $1", learner_id)
                await conn.execute("DELETE FROM engram_audit WHERE learner_id = $1", learner_id)
                await conn.execute(
                    "DELETE FROM engram_voice_sessions WHERE learner_id = $1", learner_id
                )
