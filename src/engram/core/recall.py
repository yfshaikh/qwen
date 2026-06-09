"""Recall — token-budgeted subgraph retrieval (DESIGN §4.4).

The fast, hot read path. A tutor turn asks "what matters about this learner +
this topic right now" and gets back a small, token-budgeted subgraph: a
``text_block`` for the prompt and a structured ``subgraph`` for the viz. There is
**no LLM reasoning** on this path — the only model call is one embedding of the
query (cached aggressively in production). Everything else is a vector query, a
bounded 1-hop traversal, a recency/importance/relevance score, and greedy
budget-filling.

The Memory Keeper has already distilled raw history into the graph, so Recall
never reads transcripts — only nodes + their top evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engram.core.models import AuditEntry, Edge, Evidence, Node, RecallResult
from engram.core.ports import LLMPort, StoragePort

# Generative-Agents-style weighting (DESIGN §4.4 step 4): recency · importance ·
# relevance. Tuned empirically with the eval harness; overridable per call.
DEFAULT_WEIGHTS: dict[str, float] = {"recency": 0.34, "importance": 0.33, "relevance": 0.33}

# Bounds that keep the hot path cheap (DESIGN §4.4: bounded vector query + hop).
_SEED_K = 8
_MAX_CANDIDATES = 20
_TOP_EVIDENCE = 2  # evidence snippets emitted per node line
_EVIDENCE_SAMPLE = 5  # evidence rows fetched to average importance


def _chars_to_tokens(text: str) -> int:
    """Approximate token count as ``len(text) // 4`` (DESIGN §4.4 step 5)."""
    return len(text) // 4


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _fmt(x: float | None, ndigits: int = 2) -> str:
    """Render a 0..1 attribute compactly, or ``?`` when unknown."""
    return "?" if x is None else f"{round(x, ndigits):g}"


@dataclass(slots=True)
class _Candidate:
    node: Node
    relevance: float  # cosine similarity to the query vector
    importance: float  # mean evidence importance
    evidence: list[Evidence]
    evidence_count: int
    score: float = 0.0


class Recall:
    """Token-budgeted subgraph retrieval over the knowledge graph.

    Stateless aside from its weights; ``EngramService.recall`` holds one instance
    and calls :meth:`recall` per turn.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    async def recall(
        self,
        storage: StoragePort,
        llm: LLMPort,
        learner_id: str,
        query: str,
        budget: int = 600,
        *,
        weights: dict[str, float] | None = None,
    ) -> RecallResult:
        """Assemble a token-budgeted subgraph for ``query`` (DESIGN §4.4).

        Returns an empty result when the learner has no (non-forgotten) concept
        nodes matching the query.
        """
        w = self.weights if weights is None else {**self.weights, **weights}

        # 1. Embed the query (the only model call on this path).
        qvec = (await llm.embed([query]))[0]

        # 2. pgvector search → seed concept nodes by relevance.
        seeds = await storage.vector_search(learner_id, qvec, k=_SEED_K, types=["concept"])
        if not seeds:
            return RecallResult(text_block="", subgraph={"nodes": [], "edges": []})

        # 3. Bounded 1-hop expansion along edges → connected / cross-document context.
        seed_ids = [n.id for n, _ in seeds if n.id]
        edges = await storage.get_edges(learner_id, node_ids=seed_ids)

        relevance: dict[str, float] = {nid: 0.0 for nid in seed_ids}
        nodes_by_id: dict[str, Node] = {}
        for node, sim in seeds:
            if node.id:
                nodes_by_id[node.id] = node
                relevance[node.id] = sim

        seed_set = set(seed_ids)
        neighbor_ids: list[str] = []
        for e in edges:
            for nid in (e.source_id, e.target_id):
                if nid not in seed_set and nid not in nodes_by_id:
                    neighbor_ids.append(nid)
        # De-dupe while preserving order, then cap total candidate count.
        seen: set[str] = set()
        for nid in neighbor_ids:
            if nid in seen:
                continue
            seen.add(nid)
            if len(nodes_by_id) >= _MAX_CANDIDATES:
                break
            node = await storage.get_node(nid)
            if node is None or node.forgotten_at is not None:
                continue
            nodes_by_id[nid] = node
            # Neighbors weren't returned by vector_search; recompute relevance.
            relevance[nid] = _cosine(qvec, node.embedding) if node.embedding else 0.0

        # 4. Score each candidate: w_r·recency + w_i·importance + w_v·relevance.
        candidates: list[_Candidate] = []
        for nid, node in nodes_by_id.items():
            ev = await storage.get_evidence(nid, limit=_EVIDENCE_SAMPLE)
            importances = [e.importance for e in ev if e.importance is not None]
            importance = float(np.mean(importances)) if importances else 0.0
            counts = await storage.evidence_counts([nid])
            recency = node.salience or 0.0  # normalized activation, default 0
            rel = relevance.get(nid, 0.0)
            cand = _Candidate(
                node=node,
                relevance=rel,
                importance=importance,
                evidence=ev,
                evidence_count=counts.get(nid, len(ev)),
            )
            cand.score = (
                w["recency"] * recency + w["importance"] * importance + w["relevance"] * rel
            )
            candidates.append(cand)

        candidates.sort(key=lambda c: c.score, reverse=True)

        # 5. Greedily fill the token budget, best-first. Each node → one compact
        #    line + its top 1-2 evidence snippets; stop once the budget is spent.
        lines: list[str] = []
        selected: list[_Candidate] = []
        used = 0
        for cand in candidates:
            block = self._render(cand)
            cost = _chars_to_tokens(block)
            if selected and used + cost > budget:
                break  # keep at least one node even if it overflows a tiny budget
            lines.append(block)
            used += cost
            selected.append(cand)
            if used >= budget:
                break

        # 6. Build the structured subgraph (selected nodes + edges among them).
        selected_ids = {c.node.id for c in selected if c.node.id}
        node_dicts = [self._node_dict(c) for c in selected]
        edge_dicts = [
            self._edge_dict(e)
            for e in edges
            if e.source_id in selected_ids and e.target_id in selected_ids
        ]

        text_block = "\n".join(lines)

        # 7. Best-effort audit row; never fail recall if the write fails.
        await self._audit(storage, learner_id, query, len(selected))

        return RecallResult(
            text_block=text_block,
            subgraph={"nodes": node_dicts, "edges": edge_dicts},
        )

    @staticmethod
    def _render(cand: _Candidate) -> str:
        """One compact node line plus its top 1-2 evidence snippets."""
        node = cand.node
        head = (
            f"- {node.label} (mastery={_fmt(node.mastery)}, "
            f"{cand.evidence_count} ev): {node.summary or ''}".rstrip()
        )
        parts = [head]
        for ev in cand.evidence[:_TOP_EVIDENCE]:
            if ev.content:
                kind = ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind)
                parts.append(f"    • [{kind}] {ev.content}")
        return "\n".join(parts)

    @staticmethod
    def _node_dict(cand: _Candidate) -> dict[str, object]:
        node = cand.node
        return {
            "id": node.id,
            "type": node.type.value if hasattr(node.type, "value") else str(node.type),
            "label": node.label,
            "mastery": node.mastery,
            "confidence": node.confidence,
            "salience": node.salience,
            "evidence_count": cand.evidence_count,
        }

    @staticmethod
    def _edge_dict(edge: Edge) -> dict[str, object]:
        return {
            "id": edge.id,
            "source": edge.source_id,
            "target": edge.target_id,
            "type": edge.type.value if hasattr(edge.type, "value") else str(edge.type),
            "weight": edge.weight,
        }

    @staticmethod
    async def _audit(storage: StoragePort, learner_id: str, query: str, n: int) -> None:
        try:
            await storage.insert_audit(
                AuditEntry(
                    learner_id=learner_id,
                    op="recall",
                    input_refs={"query": query},
                    output_refs={"node_count": n},
                    rationale=f"recalled {n} nodes for '{query}'",
                )
            )
        except Exception:  # noqa: BLE001 — audit is best-effort; recall must not fail.
            pass


async def recall(
    storage: StoragePort,
    llm: LLMPort,
    learner_id: str,
    query: str,
    budget: int = 600,
    *,
    weights: dict[str, float] | None = None,
) -> RecallResult:
    """Functional entry point — a thin wrapper over :class:`Recall`."""
    return await Recall(weights).recall(storage, llm, learner_id, query, budget)
