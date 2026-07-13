"""Read-only insights facade. Constructed from the storage port only; never
writes. `eng.insights` returns one of these. Deleting this package breaks
nothing in core/."""
from __future__ import annotations

from typing import Any

from engram.insights import queries, review


class Insights:
    def __init__(self, storage: Any) -> None:
        self._s = storage

    async def _live_edges(self, learner_id: str, node_ids: list[str]) -> list:
        return await self._s.get_edges(learner_id, node_ids) if node_ids else []

    async def summary(self, learner_id: str) -> dict:
        live = await self._s.get_live_nodes(learner_id)
        all_nodes = await self._s.get_all_nodes(learner_id)
        ev = await self._s.evidence_counts_by_kind(learner_id)
        edges = await self._live_edges(learner_id, [n.id for n in live])
        sessions = len(await self._s.list_voice_sessions(learner_id, 1000))
        hist = await self._s.mastery_history(learner_id)
        # ponytail: last_active == last CONSOLIDATION (mastery history is written
        # only during consolidation); a learner active-but-not-yet-consolidated
        # reads None. True last-utterance ts would need an events max() read —
        # add when the tile needs sub-consolidation freshness.
        last_active = hist[-1]["ts"] if hist else None
        return queries.summarize(live, all_nodes, len(edges), ev, sessions, last_active)

    async def mastery_timeline(self, learner_id: str,
                               node_ids: list[str] | None = None) -> dict:
        live = await self._s.get_live_nodes(learner_id)
        labels = {n.id: n.label for n in live}
        rows = await self._s.mastery_history(learner_id, node_ids)
        # mastery_history has no forgotten filter — drop history for non-live
        # nodes so the chart never shows raw-UUID-labeled forgotten series.
        rows = [r for r in rows if r["node_id"] in labels]
        return queries.timeline(rows, labels)

    async def hotspots(self, learner_id: str, k: int = 5) -> list[dict]:
        live = await self._s.get_live_nodes(learner_id)
        ev = await self._s.evidence_counts_by_kind(learner_id)
        tr = queries.trend(await self._s.mastery_history(learner_id))
        return queries.rank_hotspots(live, ev, tr, k)

    async def activity(self, learner_id: str, days: int = 30) -> list[dict]:
        return await self._s.event_counts_by_day(learner_id, days)

    async def review_queue(self, learner_id: str, k: int = 5) -> list[dict]:
        live = await self._s.get_live_nodes(learner_id)
        edges = await self._live_edges(learner_id, [n.id for n in live])
        ev = await self._s.evidence_counts_by_kind(learner_id)
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
        live = await self._s.get_live_nodes(learner_id)
        edges = await self._live_edges(learner_id, [n.id for n in live])
        return review.blockers(live, edges, target_ids)
