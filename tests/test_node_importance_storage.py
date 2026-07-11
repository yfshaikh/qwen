"""Node.importance round-trips through FakeStorage, plans, and fixture dicts."""
from engram.core.consolidation import ConsolidationPlan
from engram.core.models import Node, NodeType
from engram.eval.fixtures import load_graph_into, node_to_dict, snapshot_graph
from tests.fakes import FakeStorage


def _node(label="A", importance=None):
    return Node(learner_id="L", type=NodeType.CONCEPT, label=label,
                importance=importance, salience=1.0)


async def test_fake_storage_persists_importance_on_update():
    storage = FakeStorage()
    nid = await storage.insert_node(_node(importance=0.2))
    upd = (await storage.get_live_nodes("L"))[0]
    upd.importance = 0.9
    await storage.apply_consolidation(
        ConsolidationPlan(learner_id="L", node_updates=[upd]))
    assert storage.nodes[nid].importance == 0.9


async def test_fixture_round_trip_carries_importance():
    storage = FakeStorage()
    await storage.insert_node(_node(importance=0.7))
    graph = await snapshot_graph(storage, "L")
    assert graph["nodes"][0]["importance"] == 0.7
    await load_graph_into(storage, graph, "L2")
    n2 = (await storage.get_live_nodes("L2"))[0]
    assert n2.importance == 0.7


def test_node_default_importance_is_none():
    assert _node().importance is None
    assert node_to_dict(_node())["importance"] is None
