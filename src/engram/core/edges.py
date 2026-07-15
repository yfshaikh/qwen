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


def edge_rank_case_sql(column: str) -> str:
    """Build a SQL `CASE` expression on `column` (an edge `.type` column,
    holding `EdgeType.value` strings) that reproduces `edge_rank()`'s ranking.

    Single source for PostgresStorage.merge_nodes' collision tie-break SQL, so
    the inlined `CASE` can never drift from `EDGE_RANK` (they used to be two
    hand-maintained copies). The lowest-ranked type becomes the `ELSE` default
    (matches the pre-refactor SQL, which left `relates_to` — rank 0 — implicit).
    """
    default_type, default_rank = min(EDGE_RANK.items(), key=lambda kv: kv[1])
    whens = " ".join(
        f"WHEN '{t.value}' THEN {r}"
        for t, r in sorted(EDGE_RANK.items(), key=lambda kv: -kv[1])
        if t != default_type
    )
    return f"CASE {column} {whens} ELSE {default_rank} END"
