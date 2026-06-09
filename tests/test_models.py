from datetime import datetime

from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    GraphView,
    LearningEvent,
    Message,
    Node,
    NodeType,
    RecallResult,
)


def test_learning_event_round_trip():
    e = LearningEvent(
        learner_id="alice",
        type="utterance",
        text="I don't get derivatives",
        refs={"doc_id": "calc-101", "page": 7},
        signals={"confusion": 0.8},
    )
    assert e.learner_id == "alice"
    assert e.refs["page"] == 7
    assert e.signals["confusion"] == 0.8
    assert isinstance(e.ts, datetime)
    assert e.ts.tzinfo is not None  # always tz-aware


def test_node_defaults_and_types():
    n = Node(learner_id="alice", type=NodeType.CONCEPT, label="derivatives")
    assert n.type is NodeType.CONCEPT
    assert n.mastery is None
    assert n.embedding is None
    assert n.source_refs == []
    assert n.forgotten_at is None


def test_edge_validates_type():
    edge = Edge(
        learner_id="alice",
        source_id="a",
        target_id="b",
        type=EdgeType.PREREQUISITE,
    )
    assert edge.type is EdgeType.PREREQUISITE


def test_evidence_kind_literal():
    ev = Evidence(node_id="n1", kind=EvidenceKind.QUIZ_WRONG, content="missed Q3")
    assert ev.kind is EvidenceKind.QUIZ_WRONG


def test_recall_and_graph_view_shapes():
    rv = RecallResult(text_block="...", subgraph={"nodes": [], "edges": []})
    assert rv.text_block == "..."
    gv = GraphView(nodes=[], edges=[])
    assert gv.nodes == [] and gv.edges == []


def test_message_shape():
    m = Message(role="user", content="hi")
    assert m.role == "user" and m.content == "hi"
