"""Read-path methods: vector recall, edge/node lookups, top evidence."""

from __future__ import annotations

from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Node

from ._base import _NODE_COLS, _Base, _row_to_node, _vec_to_list


class _ReadsMixin(_Base):
    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_NODE_COLS} FROM engram_nodes
                WHERE learner_id = $1 AND forgotten_at IS NULL
                ORDER BY embedding <=> $2
                LIMIT $3
                """,
                learner_id, query_vec, k,
            )
            return [_row_to_node(r) for r in rows]

    async def get_edges(self, learner_id: str, node_ids: list[str]) -> list[Edge]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, learner_id, source_id, target_id, type, weight, created_at
                FROM engram_edges
                WHERE learner_id = $1
                  AND (source_id = ANY($2::uuid[]) OR target_id = ANY($2::uuid[]))
                """,
                learner_id, node_ids,
            )
            return [
                Edge(
                    id=str(r["id"]),
                    learner_id=r["learner_id"],
                    source_id=str(r["source_id"]),
                    target_id=str(r["target_id"]),
                    type=EdgeType(r["type"]),
                    weight=r["weight"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    async def get_nodes(self, learner_id: str, node_ids: list[str]) -> list[Node]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_NODE_COLS} FROM engram_nodes
                WHERE learner_id = $1 AND id = ANY($2::uuid[]) AND forgotten_at IS NULL
                """,
                learner_id, node_ids,
            )
            return [_row_to_node(r) for r in rows]

    async def top_evidence(
        self, node_ids: list[str], per_node: int, *, with_embedding: bool = True
    ) -> dict[str, list[Evidence]]:
        cols = ("id, node_id, kind, content, source_ref, embedding, importance, created_at"
                if with_embedding else
                "id, node_id, kind, content, source_ref, importance, created_at")
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {cols}
                FROM (
                  SELECT {cols}, row_number() OVER (
                    PARTITION BY node_id
                    ORDER BY importance DESC NULLS LAST, created_at DESC
                  ) AS rn
                  FROM engram_evidence
                  WHERE node_id = ANY($1::uuid[])
                ) t
                WHERE rn <= $2
                """,
                node_ids, per_node,
            )
        out: dict[str, list[Evidence]] = {nid: [] for nid in node_ids}
        for r in rows:
            emb = r["embedding"] if with_embedding else None
            out.setdefault(str(r["node_id"]), []).append(
                Evidence(
                    id=str(r["id"]),
                    node_id=str(r["node_id"]),
                    kind=EvidenceKind(r["kind"]),
                    content=r["content"],
                    source_ref=r["source_ref"],
                    embedding=_vec_to_list(emb),
                    importance=r["importance"],
                    created_at=r["created_at"],
                )
            )
        return out
