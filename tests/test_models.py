from datetime import datetime, timezone

from engram.core.models import (
    Completion,
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


def test_enums_have_expected_values():
    assert NodeType.CONCEPT.value == "concept"
    assert EdgeType.PREREQUISITE.value == "prerequisite"
    assert EvidenceKind.QUIZ_WRONG.value == "quiz_wrong"


def test_learning_event_defaults():
    e = LearningEvent(learner_id="alice", type="utterance", text="what is a limit?")
    assert e.refs == {}
    assert e.signals == {}
    assert e.ts.tzinfo == timezone.utc


def test_node_minimal_construction():
    n = Node(learner_id="alice", type=NodeType.CONCEPT, label="limits")
    assert n.id is None
    assert n.source_refs == []
    assert isinstance(n.created_at, datetime)


def test_edge_and_evidence_and_views():
    edge = Edge(learner_id="alice", source_id="a", target_id="b", type=EdgeType.RELATES_TO)
    assert edge.weight == 1.0
    ev = Evidence(node_id="n1", kind=EvidenceKind.STRUGGLE)
    assert ev.importance is None
    rr = RecallResult(text_block="ctx", subgraph={"nodes": [], "edges": []})
    assert rr.text_block == "ctx"
    gv = GraphView(nodes=[], edges=[])
    assert gv.nodes == []


def test_message_and_completion():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    c = Completion(text="hello", usage={"total_tokens": 3}, model="fake")
    assert c.json is None
    assert c.usage["total_tokens"] == 3
