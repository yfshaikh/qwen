from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, LearningEvent, Node, NodeType
from tests.fakes import FakeStorage

async def test_delete_learner_removes_only_that_learner():
    s = FakeStorage()
    a = await s.insert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0]))
    b = await s.insert_node(Node(learner_id="b", type=NodeType.CONCEPT, label="B", embedding=[1.0]))
    await s.insert_edge(Edge(learner_id="a", source_id=a, target_id=a, type=EdgeType.RELATES_TO))
    await s.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.NOTE, content="x"))
    await s.insert_event(LearningEvent(learner_id="a", type="utterance", text="hi"))

    await s.delete_learner("a")

    assert await s.get_live_nodes("a") == []
    assert [n.id for n in await s.get_live_nodes("b")] == [b]
    assert s.edges == []
    assert s.evidence == []
    assert await s.get_events("a") == []
