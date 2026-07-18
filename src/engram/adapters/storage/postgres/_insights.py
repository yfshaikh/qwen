"""Insight read methods: mastery history, evidence/event counts."""

from __future__ import annotations

from datetime import datetime

from ._base import _Base


class _InsightsMixin(_Base):
    async def mastery_history(self, learner_id: str, node_ids: list[str] | None = None,
                              since: datetime | None = None) -> list[dict]:
        q = ("SELECT h.node_id, h.mastery, h.confidence, h.ts"
             " FROM engram_mastery_history h JOIN engram_nodes n ON n.id = h.node_id"
             " WHERE n.learner_id = $1")
        params: list = [learner_id]
        if node_ids is not None:
            # pass raw str ids into ::uuid[] — same as get_edges/get_nodes (:221, :243);
            # NO uuid.UUID() conversion (keeps this method uuid-import-free).
            params.append(node_ids)
            q += f" AND h.node_id = ANY(${len(params)}::uuid[])"
        if since is not None:
            params.append(since)
            q += f" AND h.ts >= ${len(params)}"
        q += " ORDER BY h.ts"
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(q, *params)
        return [{"node_id": str(r["node_id"]), "mastery": r["mastery"],
                 "confidence": r["confidence"], "ts": r["ts"]} for r in rows]

    async def evidence_counts_by_kind(self, learner_id: str) -> list[dict]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT e.node_id, e.kind, count(*) AS c FROM engram_evidence e"
                " JOIN engram_nodes n ON n.id = e.node_id WHERE n.learner_id = $1"
                " GROUP BY e.node_id, e.kind", learner_id)
        return [{"node_id": str(r["node_id"]), "kind": r["kind"], "count": r["c"]} for r in rows]

    async def last_event_at(self, learner_id: str) -> datetime | None:
        async with self._require_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT max(ts) FROM engram_events WHERE learner_id = $1", learner_id
            )

    async def count_voice_sessions(self, learner_id: str) -> int:
        async with self._require_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM engram_voice_sessions WHERE learner_id = $1",
                learner_id,
            )
            return int(count)

    async def event_counts_by_day(self, learner_id: str, days: int = 30) -> list[dict]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                # bucket in UTC explicitly so day boundaries match FakeStorage
                # (which uses .date() on tz-aware UTC datetimes) regardless of the
                # server's timezone GUC.
                "SELECT date_trunc('day', ts AT TIME ZONE 'UTC')::date AS day,"
                " count(*) AS c FROM engram_events"
                " WHERE learner_id = $1 AND ts >= now() - make_interval(days => $2)"
                " GROUP BY day ORDER BY day", learner_id, days)
        return [{"day": r["day"], "count": r["c"]} for r in rows]
