"""Read-only insights facade. Constructed from the storage port only; never
writes. Callers construct `Insights(storage)` directly at the app layer
(see app/main.py). Deleting this package breaks nothing in core/.

None of these queries read `node.embedding`, so every node fetch here passes
`with_embedding=False` — same rows, minus the ~1024-float vector column.
Independent awaits (ones that don't consume each other's result) are fired
together via `asyncio.gather` to cut round-trip latency; awaits that need a
prior result (e.g. `get_edges` needs the live node ids) stay sequential.
"""
from __future__ import annotations

import asyncio
from typing import Any

from engram.insights import queries, review


class Insights:
    def __init__(self, storage: Any) -> None:
        self._s = storage

    async def _live_edges(self, learner_id: str, node_ids: list[str]) -> list:
        return await self._s.get_edges(learner_id, node_ids) if node_ids else []

    async def summary(self, learner_id: str) -> dict:
        all_nodes, ev, sessions, last_active = await asyncio.gather(
            self._s.get_all_nodes(learner_id, with_embedding=False),
            self._s.evidence_counts_by_kind(learner_id),
            self._s.count_voice_sessions(learner_id),
            self._s.last_event_at(learner_id),
        )
        live = [n for n in all_nodes if n.forgotten_at is None]
        edges = await self._live_edges(learner_id, [n.id for n in live])
        return queries.summarize(live, all_nodes, len(edges), ev, sessions, last_active)

    async def mastery_timeline(self, learner_id: str,
                               node_ids: list[str] | None = None) -> dict:
        live, rows = await asyncio.gather(
            self._s.get_live_nodes(learner_id, with_embedding=False),
            self._s.mastery_history(learner_id, node_ids),
        )
        labels = {n.id: n.label for n in live}
        # mastery_history has no forgotten filter — drop history for non-live
        # nodes so the chart never shows raw-UUID-labeled forgotten series.
        rows = [r for r in rows if r["node_id"] in labels]
        return queries.timeline(rows, labels)

    async def hotspots(self, learner_id: str, k: int = 5) -> list[dict]:
        live, ev, hist = await asyncio.gather(
            self._s.get_live_nodes(learner_id, with_embedding=False),
            self._s.evidence_counts_by_kind(learner_id),
            self._s.mastery_history(learner_id),
        )
        tr = queries.trend(hist)
        return queries.rank_hotspots(live, ev, tr, k)

    async def activity(self, learner_id: str, days: int = 30) -> list[dict]:
        return await self._s.event_counts_by_day(learner_id, days)

    async def review_queue(self, learner_id: str, k: int = 5) -> list[dict]:
        live, ev = await asyncio.gather(
            self._s.get_live_nodes(learner_id, with_embedding=False),
            self._s.evidence_counts_by_kind(learner_id),
        )
        edges = await self._live_edges(learner_id, [n.id for n in live])
        # SUM across kinds — a node can have both quiz_wrong AND struggle rows.
        # (A dict comprehension would be last-wins; that disagrees with
        # queries.rank_hotspots, which sums.)
        struggle: dict[str, int] = {}
        for r in ev:
            if r["kind"] in ("quiz_wrong", "struggle"):
                struggle[r["node_id"]] = struggle.get(r["node_id"], 0) + r["count"]
        return review.review_queue(live, edges, struggle, k)

    async def blockers(self, learner_id: str,
                       target_ids: list[str] | None = None) -> list[dict]:
        live = await self._s.get_live_nodes(learner_id, with_embedding=False)
        edges = await self._live_edges(learner_id, [n.id for n in live])
        return review.blockers(live, edges, target_ids)
