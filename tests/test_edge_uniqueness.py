"""The undirected edge-pair uniqueness guardrail (migration 0004).

FakeStorage mirrors the DB index by raising ValueError; the live index itself
is exercised in tests/test_storage_postgres.py (Docker-only).
"""
import pytest

from engram.core.consolidation import ConsolidationPlan
from engram.core.models import Edge, EdgeType, Node, NodeType
from tests.fakes import FakeStorage


async def _two_nodes(storage):
    a = await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT, label="A"))
    b = await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT, label="B"))
    return a, b


async def test_insert_edge_rejects_duplicate_pair_either_direction():
    storage = FakeStorage()
    a, b = await _two_nodes(storage)
    await storage.insert_edge(Edge(learner_id="L", source_id=a, target_id=b,
                                   type=EdgeType.RELATES_TO))
    with pytest.raises(ValueError, match="duplicate edge pair"):
        await storage.insert_edge(Edge(learner_id="L", source_id=b, target_id=a,
                                       type=EdgeType.PREREQUISITE))


async def test_apply_consolidation_rejects_duplicate_new_edge():
    storage = FakeStorage()
    a, b = await _two_nodes(storage)
    await storage.insert_edge(Edge(learner_id="L", source_id=a, target_id=b,
                                   type=EdgeType.RELATES_TO))
    plan = ConsolidationPlan(learner_id="L", new_edges=[
        Edge(learner_id="L", source_id=a, target_id=b, type=EdgeType.RELATES_TO)])
    with pytest.raises(ValueError, match="duplicate edge pair"):
        await storage.apply_consolidation(plan)


async def test_other_learner_same_pair_ok():
    storage = FakeStorage()
    a, b = await _two_nodes(storage)
    await storage.insert_edge(Edge(learner_id="L", source_id=a, target_id=b,
                                   type=EdgeType.RELATES_TO))
    # same node ids under a different learner id are a different pair row
    await storage.insert_edge(Edge(learner_id="M", source_id=a, target_id=b,
                                   type=EdgeType.RELATES_TO))
    assert len(storage.edges) == 2
