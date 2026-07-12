"""mypy probe: the consumer-visible types actually propagate. Not a pytest
module — it's in mypy's files list so CI type-checks the consumer experience."""
from engram import AuditRow, Engram, GraphView, RecallResult, ScoredNode, Subgraph


async def recall_text(eng: Engram, learner_id: str) -> str:
    # Engram must be a real class to mypy, not Any (a module __getattr__ would
    # silently type it Any and this probe couldn't tell) — so exercise a method
    # signature that only type-checks against the actual class.
    res: RecallResult = await eng.recall(learner_id, "query", budget=100)
    return res.text_block


def first_label(res: RecallResult) -> str | None:
    nodes: list[ScoredNode] = res.subgraph["nodes"]
    return nodes[0]["label"] if nodes else None


def audit_cost(rows: list[AuditRow]) -> float:
    return sum(r["cost"] or 0.0 for r in rows)


def graph_size(gv: GraphView) -> int:
    return len(gv.nodes) + len(gv.edges)


_sg: Subgraph = {"nodes": [], "edges": []}
