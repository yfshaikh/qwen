"""Shared edge-type precedence (Keeper link step + merge_nodes dedup)."""
from __future__ import annotations

from engram.core.models import EdgeType

EDGE_RANK: dict[EdgeType, int] = {
    EdgeType.RELATES_TO: 0,
    EdgeType.PART_OF: 1,
    EdgeType.PREREQUISITE: 2,
}


def edge_rank(t: EdgeType | str) -> int:
    if isinstance(t, str):
        t = EdgeType(t)
    return EDGE_RANK[t]
