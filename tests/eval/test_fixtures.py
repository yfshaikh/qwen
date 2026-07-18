import json

from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Node, NodeType
from engram.eval import fixtures
from tests.fakes import FakeStorage


async def _seed(s, learner):
    a = await s.insert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="Limit",
                                 mastery=0.1, salience=1.0, embedding=[1.0, 0.0]))
    b = await s.insert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="Calculus",
                                 salience=1.0, embedding=[0.0, 1.0]))
    await s.insert_edge(Edge(learner_id=learner, source_id=a, target_id=b, type=EdgeType.PART_OF))
    await s.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.QUIZ_WRONG, content="said 2"))
    return a, b


async def test_snapshot_then_load_remaps_ids():
    src = FakeStorage()
    a, b = await _seed(src, "orig")
    graph = await fixtures.snapshot_graph(src, "orig")
    assert {n["label"] for n in graph["nodes"]} == {"Limit", "Calculus"}

    dst = FakeStorage()
    idmap = await fixtures.load_graph_into(dst, graph, "eval:x:1")
    nodes = await dst.get_live_nodes("eval:x:1")
    assert {n.label for n in nodes} == {"Limit", "Calculus"}
    # edge references remapped ids, not the originals
    edge = dst.edges[0]
    assert edge.source_id == idmap[a] and edge.target_id == idmap[b]
    assert edge.learner_id == "eval:x:1"
    assert dst.evidence[0].node_id == idmap[a]
    assert dst.evidence[0].kind == EvidenceKind.QUIZ_WRONG


async def test_save_load_roundtrip(tmp_path):
    src = FakeStorage()
    await _seed(src, "orig")
    graph = await fixtures.snapshot_graph(src, "orig")
    p = tmp_path / "f.json"
    fixtures.save_fixture(p, scenario_id="s", sessions=[{"turns": []}], graph=graph)
    loaded = fixtures.load_fixture(p)
    assert loaded["scenario_id"] == "s"
    assert loaded["graph"]["nodes"][0]["embedding"]  # embeddings preserved
    assert json.loads(p.read_text())["graph"]["edges"]


async def test_snapshot_includes_forgotten_when_asked():
    from datetime import datetime, timezone
    from engram.core.models import Node, NodeType
    from engram.eval.fixtures import snapshot_graph
    from tests.fakes import FakeStorage

    s = FakeStorage()
    await s.insert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="Live",
                             salience=0.9, embedding=[1.0] * 4))
    dead = Node(learner_id="a", type=NodeType.CONCEPT, label="Dead",
                salience=0.01, embedding=[1.0] * 4,
                forgotten_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    await s.insert_node(dead)

    live_only = await snapshot_graph(s, "a")
    assert [n["label"] for n in live_only["nodes"]] == ["Live"]

    both = await snapshot_graph(s, "a", include_forgotten=True)
    labels = {n["label"]: n["forgotten_at"] for n in both["nodes"]}
    assert labels["Live"] is None
    assert labels["Dead"].startswith("2026-02-01")
