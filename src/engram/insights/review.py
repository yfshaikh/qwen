"""Pure review-queue scoring and prerequisite-blocker walk. No I/O.

Edge convention: (source_id -> target_id, prerequisite) == source is a
prerequisite OF target. Verify against a real consolidated graph before
relying on blocked-path UI; if inverted, swap _dependents/_prerequisites."""
from __future__ import annotations

from engram.core.models import Edge, EdgeType, Node

# ponytail: fixed weights; adaptive-recall spec can learn these later.
_W_WEAK, _W_FADING, _W_UNLOCKS, _W_STRUGGLE = 0.40, 0.25, 0.20, 0.15
_WEAK_MASTERY = 0.6  # a node counts as "weak" (and unlockable) below this


def _prereq_edges(edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e.type == EdgeType.PREREQUISITE]


def _dependents(node_id: str, edges: list[Edge]) -> list[str]:
    return [e.target_id for e in _prereq_edges(edges) if e.source_id == node_id]


def _prerequisites(node_id: str, edges: list[Edge]) -> list[str]:
    return [e.source_id for e in _prereq_edges(edges) if e.target_id == node_id]


def due_score(node: Node, unlocks: int, struggle: int) -> float:
    weak = 1.0 - (node.mastery if node.mastery is not None else 0.0)
    fading = 1.0 - (node.salience if node.salience is not None else 1.0)
    return round(_W_WEAK * weak + _W_FADING * fading
                 + _W_UNLOCKS * min(unlocks, 5) / 5.0
                 + _W_STRUGGLE * min(struggle, 5) / 5.0, 4)


def _reason(node: Node, unlocks: int, struggle: int) -> str:
    parts = []
    m = node.mastery
    if m is not None and m < _WEAK_MASTERY:
        parts.append(f"weak ({round(m * 100)}%)")
    if unlocks:
        parts.append(f"prerequisite of {unlocks} struggling concept{'s' if unlocks != 1 else ''}")
    if struggle:
        parts.append(f"recent struggle ({struggle})")
    # None salience == no decay signal == not fading (matches due_score and
    # queries.summarize); `or 1.0` would also swallow a real salience of 0.0.
    if (node.salience if node.salience is not None else 1.0) < 0.3:
        parts.append("fading")
    return " and ".join(parts) or "due for review"


def review_queue(nodes: list[Node], edges: list[Edge],
                 struggle_by_node: dict[str, int], k: int = 5) -> list[dict]:
    live: dict[str, Node] = {n.id: n for n in nodes if n.id}
    weak_ids = {nid for nid, n in live.items()
                if (n.mastery if n.mastery is not None else 0.0) < _WEAK_MASTERY}
    scored: list[dict] = []
    for nid, n in live.items():
        unlocks = sum(1 for t in _dependents(nid, edges) if t in weak_ids)
        struggle = struggle_by_node.get(nid, 0)
        scored.append({
            "node_id": nid, "label": n.label,
            "score": due_score(n, unlocks, struggle),
            "reason": _reason(n, unlocks, struggle),
        })
    scored.sort(key=lambda d: (-d["score"], d["label"]))
    return scored[:k]


def blockers(nodes: list[Node], edges: list[Edge],
             target_ids: list[str] | None = None) -> list[dict]:
    live: dict[str, Node] = {n.id: n for n in nodes if n.id}
    if not live:
        return []
    if not target_ids:
        # top-importance concepts stand in for goals when none are given.
        target_ids = [n.id for n in sorted(
            live.values(), key=lambda n: -(n.importance or 0.0))[:3] if n.id]
    out: dict[str, dict] = {}
    for tgt in target_ids:
        # walk backward over prerequisites (stack/DFS via frontier.pop()),
        # collecting weak ancestors; first path to reach a node wins (mastery is
        # per-node, so the < guard only ever fires on first insertion).
        seen, frontier = {tgt}, [(tgt, [tgt])]
        while frontier:
            cur, path = frontier.pop()
            for pre in _prerequisites(cur, edges):
                if pre in seen or pre not in live:
                    continue
                seen.add(pre)
                node = live[pre]
                if (node.mastery if node.mastery is not None else 1.0) < _WEAK_MASTERY:
                    if pre not in out or (node.mastery or 0) < out[pre]["mastery"]:
                        out[pre] = {"node_id": pre, "label": node.label,
                                    "mastery": node.mastery or 0.0, "path": path + [pre]}
                frontier.append((pre, path + [pre]))
    return sorted(out.values(), key=lambda b: b["mastery"])
