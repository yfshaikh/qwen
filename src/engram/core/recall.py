"""Recall — the token-budgeted subgraph read path (DESIGN.md §4.4).

No LLM on this path: one embedding for the query, a vector seed, a bounded graph
expansion, Python-side scoring, and a greedy token-budget fill. Dependencies
(storage, embedder, token counter, weights) are injected so the whole thing is
unit-testable with fakes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from engram.core.models import Edge, Evidence, Node, RecallResult
from engram.core.ports import EmbedderPort, StoragePort
from engram.core.tokens import TokenCounter


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(slots=True)
class RecallWeights:
    recency: float = 0.3
    importance: float = 0.3
    relevance: float = 0.4


_NEEDS_ATTENTION = 0.4  # mastery below this leads the text_block (#2)
_BUFFER_N = 6  # last N signal-bearing pending events shown to the tutor (#1)


class Recall:
    def __init__(
        self,
        storage: StoragePort,
        embedder: EmbedderPort,
        token_count: TokenCounter,
        weights: RecallWeights,
        seed_k: int = 8,
        hops: int = 2,
        fanout: int = 10,
        per_node_evidence: int = 2,
        session_buffer: bool = True,
    ) -> None:
        self.storage = storage
        self.embedder = embedder
        self.token_count = token_count
        self.w = weights
        self.seed_k = seed_k
        self.hops = hops
        self.fanout = fanout
        self.per_node_evidence = per_node_evidence
        self.session_buffer = session_buffer

    async def run(self, learner_id: str, query: str, budget: int) -> RecallResult:
        if not query.strip():
            return RecallResult(text_block="", subgraph={"nodes": [], "edges": []})

        query_vec = (await self.embedder.embed([query]))[0]
        seeds = await self.storage.vector_search(learner_id, query_vec, self.seed_k)
        nodes_by_id, edges = await self._expand(learner_id, seeds)
        ev_map = await self.storage.top_evidence(
            list(nodes_by_id), self.per_node_evidence
        )

        scored = self._score(query_vec, nodes_by_id, ev_map)
        result = self._fill(scored, edges, ev_map, budget)
        if self.session_buffer:
            remaining = budget - self.token_count(result.text_block)
            # Bound the hot-path fetch: buffer only keeps last _BUFFER_N
            # signal-bearing events; over-fetch a little for non-signal noise.
            pending = await self.storage.get_pending_events(
                learner_id, limit=_BUFFER_N * 8)
            tail = self._session_buffer_block(pending, remaining)
            if tail:
                joined = f"{result.text_block}\n{tail}" if result.text_block else tail
                result.text_block = joined
        return result

    async def _expand(
        self, learner_id: str, seeds: list[Node]
    ) -> tuple[dict[str, Node], list[Edge]]:
        nodes_by_id: dict[str, Node] = {n.id: n for n in seeds if n.id}
        edges_seen: dict[str, Edge] = {}
        frontier = list(nodes_by_id.keys())

        for _ in range(self.hops):
            if not frontier:
                break
            hop_edges = await self.storage.get_edges(learner_id, frontier)
            per_node: dict[str, int] = {fid: 0 for fid in frontier}
            to_fetch: list[str] = []
            for e in hop_edges:
                edges_seen[e.id or f"{e.source_id}->{e.target_id}"] = e
                for near, far in ((e.source_id, e.target_id), (e.target_id, e.source_id)):
                    if near in per_node and per_node[near] < self.fanout:
                        if far not in nodes_by_id and far not in to_fetch:
                            per_node[near] += 1
                            to_fetch.append(far)
            next_frontier: list[str] = []
            if to_fetch:
                for n in await self.storage.get_nodes(learner_id, to_fetch):
                    if n.id:
                        nodes_by_id[n.id] = n
                        next_frontier.append(n.id)
            frontier = next_frontier

        return nodes_by_id, list(edges_seen.values())

    def _score(
        self,
        query_vec: list[float],
        nodes_by_id: dict[str, Node],
        ev_map: dict[str, list[Evidence]],
    ) -> list[tuple[float, Node, dict[str, float]]]:
        scored: list[tuple[float, Node, dict[str, float]]] = []
        for nid, node in nodes_by_id.items():
            relevance = (
                cosine_similarity(query_vec, node.embedding) if node.embedding else 0.0
            )
            recency = node.salience or 0.0
            evs = ev_map.get(nid, [])
            if node.importance is not None:
                importance = node.importance
            else:
                imps = [e.importance for e in evs if e.importance is not None]
                importance = max(imps) if imps else 0.3  # neutral prior for old graphs
            score = (
                self.w.recency * recency
                + self.w.importance * importance
                + self.w.relevance * relevance
            )
            sub = {"recency": recency, "importance": importance, "relevance": relevance}
            scored.append((score, node, sub))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored

    def _fill(
        self,
        scored: list[tuple[float, Node, dict[str, float]]],
        edges: list[Edge],
        ev_map: dict[str, list[Evidence]],
        budget: int,
    ) -> RecallResult:
        header = "Needs attention:"
        weak_lines: list[str] = []
        lines: list[str] = []
        chosen: list[tuple[float, Node, dict[str, float]]] = []
        used = 0
        for score, node, sub in scored:
            evs = ev_map.get(node.id or "", [])
            weak = node.mastery is not None and node.mastery < _NEEDS_ATTENTION
            block = self._format_weak_node(node, evs) if weak else self._format_node(node, evs)
            cost = self.token_count(block)
            if weak and not weak_lines:
                cost += self.token_count(header)
            if used + cost > budget:
                break
            used += cost
            (weak_lines if weak else lines).append(block)
            chosen.append((score, node, sub))

        # If nothing fit but candidates exist, surface the top node in the
        # subgraph (so the console shows "found but didn't fit").
        sub_source = chosen if chosen else scored[:1]
        included_ids = {n.id for _, n, _ in sub_source}
        sub_nodes = [
            self._node_dict(score, node, sub, ev_map.get(node.id or "", []))
            for score, node, sub in sub_source
        ]
        sub_edges = [
            {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "type": e.type.value,
                "weight": e.weight,
            }
            for e in edges
            if e.source_id in included_ids and e.target_id in included_ids
        ]
        parts = ([header] + weak_lines if weak_lines else []) + lines
        return RecallResult(
            text_block="\n".join(parts),
            subgraph={"nodes": sub_nodes, "edges": sub_edges},
        )

    def _session_buffer_block(self, events, remaining: int) -> str:
        """Trailing 'this session' section from un-consolidated events. Pure string
        work — no LLM. Included inside the budget; truncated oldest-first (#1)."""
        def signal_bearing(e) -> bool:
            if e.type in ("quiz_result", "note"):
                return True
            return e.type == "utterance" and bool(e.signals)

        sig = [e for e in events if signal_bearing(e)][-_BUFFER_N:]
        if not sig or remaining <= 0:
            return ""
        header = "This session (not yet consolidated):"
        lines = []
        for e in sig:
            bits = (e.text or "").strip().replace("\n", " ")[:100]
            notes = ", ".join(f"{k}={v}" for k, v in sorted((e.signals or {}).items()))
            if notes:
                bits += f" [{notes}]"
            lines.append(f"  • {e.type}: {bits}")
        while lines and self.token_count("\n".join([header] + lines)) > remaining:
            lines.pop(0)
        return "\n".join([header] + lines) if lines else ""

    @staticmethod
    def _format_weak_node(node: Node, evs: list[Evidence]) -> str:
        line = f"- {node.label} (mastery {node.mastery:.0%})"
        snippet = next((e.content for e in evs if e.content), None)
        if snippet:
            line += f" — {snippet}"
        return line

    @staticmethod
    def _format_node(node: Node, evs: list[Evidence]) -> str:
        head = f"- {node.label} [{node.type.value}]"
        bits = []
        if node.mastery is not None:
            bits.append(f"mastery={node.mastery:.2f}")
        if node.salience is not None:
            bits.append(f"salience={node.salience:.2f}")
        if bits:
            head += " " + " ".join(bits)
        out = [head]
        for e in evs:
            out.append(f"  • {e.kind.value}: {e.content}")
        return "\n".join(out)

    @staticmethod
    def _node_dict(
        score: float, node: Node, sub: dict[str, float], evs: list[Evidence]
    ) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": node.type.value,
            "label": node.label,
            "mastery": node.mastery,
            "confidence": node.confidence,
            "salience": node.salience,
            "importance": node.importance,
            "score": score,
            "scores": sub,
            "evidence": [
                {"kind": e.kind.value, "content": e.content, "importance": e.importance}
                for e in evs
            ],
        }
