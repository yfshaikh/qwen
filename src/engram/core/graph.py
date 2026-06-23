"""Graph read — assemble a learner's knowledge graph for the console (DESIGN §4.6).

Whole graph by default; a bounded neighborhood when `focus` is a node id. Rich
nodes carry their attributes plus top evidence. No LLM, no new storage methods.
"""

from __future__ import annotations

from typing import Any

from engram.core.models import Edge, Evidence, GraphView, Node


async def build_graph(
    storage: Any,
    learner_id: str,
    focus: str | None = None,
    hops: int = 2,
    per_node_evidence: int = 2,
) -> GraphView:
    if focus is None:
        nodes = await storage.get_live_nodes(learner_id)
    else:
        nodes = await _neighborhood(storage, learner_id, focus, hops)

    nodes_by_id: dict[str, Node] = {n.id: n for n in nodes if n.id}
    ids = list(nodes_by_id)
    edges = await storage.get_edges(learner_id, ids)
    edges = [e for e in edges if e.source_id in nodes_by_id and e.target_id in nodes_by_id]
    ev_map = await storage.top_evidence(ids, per_node_evidence)

    return GraphView(
        nodes=[_node_dict(n, ev_map.get(n.id or "", [])) for n in nodes_by_id.values()],
        edges=[_edge_dict(e) for e in edges],
    )


async def _neighborhood(storage: Any, learner_id: str, focus: str, hops: int) -> list[Node]:
    seeds = await storage.get_nodes(learner_id, [focus])
    collected: dict[str, Node] = {n.id: n for n in seeds if n.id}
    frontier = list(collected)
    for _ in range(hops):
        if not frontier:
            break
        edges = await storage.get_edges(learner_id, frontier)
        neighbor_ids = {
            far
            for e in edges
            for near, far in ((e.source_id, e.target_id), (e.target_id, e.source_id))
            if near in collected and far not in collected
        }
        if not neighbor_ids:
            break
        frontier = []
        for n in await storage.get_nodes(learner_id, list(neighbor_ids)):
            if n.id and n.id not in collected:
                collected[n.id] = n
                frontier.append(n.id)
    return list(collected.values())


def _node_dict(node: Node, evs: list[Evidence]) -> dict[str, Any]:
    return {
        "id": node.id,
        "label": node.label,
        "type": node.type.value,
        "summary": node.summary,
        "mastery": node.mastery,
        "confidence": node.confidence,
        "salience": node.salience,
        "evidence": [
            {"kind": e.kind.value, "content": e.content, "importance": e.importance}
            for e in evs
        ],
    }


def _edge_dict(e: Edge) -> dict[str, Any]:
    return {
        "id": e.id,
        "source": e.source_id,
        "target": e.target_id,
        "type": e.type.value,
        "weight": e.weight,
    }
