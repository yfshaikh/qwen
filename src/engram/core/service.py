"""EngramService — the core's outward API (the HostPort implementation).

Composes the two ports (storage + llm) with the Recall reader and the Memory
Keeper writer, and exposes the four host operations from DESIGN §4.6 plus two
conveniences (audit feed, cron sweep). Host adapters (the text tutor, a future
voice loop, a Marfini adapter) talk only to this surface; they never touch
adapters or the graph directly.
"""

from __future__ import annotations

from typing import Any

from engram.core.keeper import Keeper
from engram.core.models import AuditEntry, GraphView, LearningEvent, Node, RecallResult
from engram.core.ports import LLMPort, StoragePort
from engram.core.recall import Recall

# Cap on nodes returned by graph() so a large graph never dumps thousands of
# nodes into the viz (DESIGN §4.8: bounded view).
_MAX_GRAPH_NODES = 60


class EngramService:
    """Implements ``core.ports.HostPort`` over a storage + llm pair."""

    def __init__(
        self,
        storage: StoragePort,
        llm: LLMPort,
        *,
        recall_weights: dict[str, float] | None = None,
        **keeper_tuning: Any,
    ) -> None:
        self.storage = storage
        self.llm = llm
        self._recall = Recall(recall_weights)
        self._keeper = Keeper(storage, llm, **keeper_tuning)

    # --- host → core ---------------------------------------------------- #
    async def ingest(self, events: list[LearningEvent]) -> list[str]:
        """Append raw learning events (the agnostic seam). Returns their ids."""
        return await self.storage.insert_events(events)

    async def recall(self, learner_id: str, query: str, budget: int = 600) -> RecallResult:
        """Token-budgeted subgraph for a tutor turn (no LLM reasoning)."""
        return await self._recall.recall(self.storage, self.llm, learner_id, query, budget)

    async def consolidate(self, learner_id: str) -> dict[str, Any]:
        """Run the Memory Keeper over the learner's pending events (idempotent)."""
        return await self._keeper.consolidate(learner_id)

    async def graph(
        self, learner_id: str, focus: str | None = None, hops: int = 1
    ) -> GraphView:
        """Render-ready bounded view for React Flow (DESIGN §4.8).

        Without ``focus``: the top nodes by salience. With ``focus`` (a node id
        or label): that node plus everything within ``hops`` edges of it.
        Forgotten (soft-deleted) nodes are excluded.
        """
        nodes = await self.storage.get_nodes(learner_id)  # salience desc, non-forgotten
        all_edges = await self.storage.get_edges(learner_id)

        if focus:
            keep = self._focus_set(focus, nodes, all_edges, hops)
            nodes = [n for n in nodes if n.id in keep]

        nodes = nodes[:_MAX_GRAPH_NODES]
        node_ids = [n.id for n in nodes if n.id]
        id_set = set(node_ids)
        counts = await self.storage.evidence_counts(node_ids)

        node_dicts = [self._node_dict(n, counts.get(n.id or "", 0)) for n in nodes]
        edge_dicts = [
            self._edge_dict(e)
            for e in all_edges
            if e.source_id in id_set and e.target_id in id_set
        ]
        return GraphView(nodes=node_dicts, edges=edge_dicts)

    async def audit(self, learner_id: str, limit: int = 100) -> list[AuditEntry]:
        """Recent memory-agent operations — provenance / 'watch it think'."""
        return await self.storage.get_audit(learner_id, limit)

    async def consolidate_sweep(self, quiet_seconds: int = 0) -> dict[str, Any]:
        """Cron backstop: consolidate every learner with quiet pending events."""
        learners = await self.storage.learners_with_pending_events(quiet_seconds)
        stats = {lid: await self.consolidate(lid) for lid in learners}
        return {"learners": learners, "stats": stats}

    # --- helpers -------------------------------------------------------- #
    @staticmethod
    def _focus_set(focus: str, nodes: list[Node], edges: list[Any], hops: int) -> set[str]:
        """Ids within ``hops`` undirected edges of the focus node (by id or label)."""
        focus_l = focus.lower()
        start = next(
            (n.id for n in nodes if n.id == focus or n.label.lower() == focus_l), None
        )
        if start is None:
            return {n.id for n in nodes if n.id}  # unknown focus → fall back to all
        adj: dict[str, set[str]] = {}
        for e in edges:
            adj.setdefault(e.source_id, set()).add(e.target_id)
            adj.setdefault(e.target_id, set()).add(e.source_id)
        keep = {start}
        frontier = {start}
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for nid in frontier:
                nxt |= adj.get(nid, set()) - keep
            keep |= nxt
            frontier = nxt
            if not frontier:
                break
        return keep

    @staticmethod
    def _node_dict(node: Node, evidence_count: int) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": node.type.value if hasattr(node.type, "value") else str(node.type),
            "label": node.label,
            "summary": node.summary,
            "mastery": node.mastery,
            "confidence": node.confidence,
            "salience": node.salience,
            "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
            "evidence_count": evidence_count,
            "forgotten_at": node.forgotten_at.isoformat() if node.forgotten_at else None,
        }

    @staticmethod
    def _edge_dict(edge: Any) -> dict[str, Any]:
        return {
            "id": edge.id,
            "source": edge.source_id,
            "target": edge.target_id,
            "type": edge.type.value if hasattr(edge.type, "value") else str(edge.type),
            "weight": edge.weight,
        }
