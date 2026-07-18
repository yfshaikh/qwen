from datetime import datetime, timezone

from engram.core.graph import build_graph
from engram.core.models import (
    Edge, EdgeType, Evidence, EvidenceKind, GraphView, Node, NodeType,
)
from tests.fakes import FakeStorage


async def _seed(fs: FakeStorage):
    # A -> B (prerequisite); C isolated; D forgotten. A has one evidence row.
    a = await fs.insert_node(Node(learner_id="x", type=NodeType.CONCEPT, label="A",
                                  summary="about A", embedding=[1.0, 0.0]))
    b = await fs.insert_node(Node(learner_id="x", type=NodeType.CONCEPT, label="B",
                                  embedding=[0.0, 1.0]))
    c = await fs.insert_node(Node(learner_id="x", type=NodeType.CONCEPT, label="C",
                                  embedding=[1.0, 1.0]))
    await fs.insert_node(Node(learner_id="x", type=NodeType.CONCEPT, label="D",
                              embedding=[0.5, 0.5], forgotten_at=datetime.now(timezone.utc)))
    await fs.insert_edge(Edge(learner_id="x", source_id=a, target_id=b,
                              type=EdgeType.PREREQUISITE))
    await fs.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.QUIZ_CORRECT,
                                      content="ok", importance=0.9))
    return a, b, c


async def test_whole_graph_nodes_edges_evidence_excludes_forgotten():
    fs = FakeStorage()
    a, b, c = await _seed(fs)
    gv = await build_graph(fs, "x")

    assert sorted(n["label"] for n in gv.nodes) == ["A", "B", "C"]  # D forgotten
    assert [(e["source"], e["target"], e["type"]) for e in gv.edges] == [(a, b, "prerequisite")]
    a_node = next(n for n in gv.nodes if n["label"] == "A")
    assert a_node["type"] == "concept"
    assert a_node["summary"] == "about A"
    assert a_node["evidence"][0] == {"kind": "quiz_correct", "content": "ok", "importance": 0.9}


async def test_focus_returns_bounded_neighborhood():
    fs = FakeStorage()
    a, b, c = await _seed(fs)
    gv = await build_graph(fs, "x", focus=a, hops=1)

    assert sorted(n["label"] for n in gv.nodes) == ["A", "B"]  # C isolated, excluded
    assert [(e["source"], e["target"]) for e in gv.edges] == [(a, b)]


async def test_unknown_learner_or_focus_is_empty():
    fs = FakeStorage()
    await _seed(fs)
    assert await build_graph(fs, "nobody") == GraphView(nodes=[], edges=[])
    assert await build_graph(fs, "x", focus="no-such-node") == GraphView(nodes=[], edges=[])
