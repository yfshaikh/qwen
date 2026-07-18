"""Low-mastery nodes lead the text_block in a 'Needs attention' section (#2)."""
from engram.core.models import Evidence, EvidenceKind, Node, NodeType
from engram.core.recall import Recall, RecallWeights
from engram.core.tokens import heuristic_token_count
from tests.fakes import FakeEmbedder, FakeStorage


async def _setup():
    storage = FakeStorage()
    weak = await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Limits", mastery=0.12,
        salience=0.5, embedding=[1.0] * 8))
    await storage.insert_evidence(Evidence(
        node_id=weak, kind=EvidenceKind.QUIZ_WRONG, content="failed the limits quiz",
        importance=0.9))
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Continuity", mastery=0.9,
        salience=0.5, embedding=[1.0] * 8))
    return storage


async def test_weak_node_renders_in_leading_section():
    storage = await _setup()
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count, RecallWeights())
    res = await r.run("L", "query", 800)
    text = res.text_block
    assert text.startswith("Needs attention:")
    assert "Limits (mastery 12%)" in text
    assert "failed the limits quiz" in text
    assert text.index("Limits") < text.index("Continuity")


async def test_no_weak_nodes_no_header():
    storage = FakeStorage()
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Continuity", mastery=0.9,
        salience=0.5, embedding=[1.0] * 8))
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count, RecallWeights())
    res = await r.run("L", "query", 800)
    assert "Needs attention" not in res.text_block


async def test_unknown_mastery_is_not_weak():
    storage = FakeStorage()
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Fresh", mastery=None,
        salience=0.5, embedding=[1.0] * 8))
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count, RecallWeights())
    res = await r.run("L", "query", 800)
    assert "Needs attention" not in res.text_block
