from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    Node,
    NodeType,
)
from engram.core.recall import Recall, RecallWeights, cosine_similarity
from engram.core.tokens import heuristic_token_count
from tests.fakes import FakeStorage


class _StubEmbedder:
    """Maps a query string to a fixed vector for deterministic relevance."""

    def __init__(self, vec):
        self.vec = vec

    async def embed(self, texts):
        return [list(self.vec) for _ in texts]


async def _seed_graph(fs: FakeStorage):
    limits = await fs.insert_node(
        Node(
            learner_id="a",
            type=NodeType.CONCEPT,
            label="Limits",
            summary="approach",
            mastery=0.7,
            salience=0.9,
            embedding=[1.0, 0.0, 0.0],
        )
    )
    derivatives = await fs.insert_node(
        Node(
            learner_id="a",
            type=NodeType.CONCEPT,
            label="Derivatives",
            salience=0.5,
            embedding=[0.0, 1.0, 0.0],
        )
    )
    await fs.insert_node(
        Node(
            learner_id="a",
            type=NodeType.CONCEPT,
            label="Cooking",
            salience=0.5,
            embedding=[0.0, 0.0, 1.0],
        )
    )
    await fs.insert_edge(
        Edge(
            learner_id="a",
            source_id=limits,
            target_id=derivatives,
            type=EdgeType.PREREQUISITE,
        )
    )
    await fs.insert_evidence(
        Evidence(
            node_id=limits,
            kind=EvidenceKind.QUIZ_CORRECT,
            content="Evaluated lim x->2.",
            importance=0.8,
        )
    )
    return limits, derivatives


def _recall(fs, seed_k=1, hops=2, budget_counter=heuristic_token_count):
    return Recall(
        storage=fs,
        embedder=_StubEmbedder([1.0, 0.0, 0.0]),
        token_count=budget_counter,
        weights=RecallWeights(),
        seed_k=seed_k,
        hops=hops,
        fanout=10,
    )


def test_cosine_basic():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


async def test_recall_seeds_and_expands_to_connected_concept():
    fs = FakeStorage()
    await _seed_graph(fs)
    res = await _recall(fs).run("a", "what is a limit", budget=800)
    # Limits is the vector seed; Derivatives reached via the prerequisite hop.
    assert "Limits" in res.text_block
    assert "Derivatives" in res.text_block
    # Cooking is neither seeded (low relevance) nor connected -> excluded.
    assert "Cooking" not in res.text_block


async def test_recall_includes_evidence_snippet():
    fs = FakeStorage()
    await _seed_graph(fs)
    res = await _recall(fs).run("a", "limit", budget=800)
    assert "Evaluated lim x->2." in res.text_block


async def test_recall_orders_by_score_and_carries_subscores():
    fs = FakeStorage()
    await _seed_graph(fs)
    res = await _recall(fs).run("a", "limit", budget=800)
    labels = [n["label"] for n in res.subgraph["nodes"]]
    assert labels[0] == "Limits"  # highest score
    top = res.subgraph["nodes"][0]
    assert top["scores"]["relevance"] == 1.0
    assert 0.0 < top["score"] <= 1.0


async def test_recall_respects_token_budget():
    fs = FakeStorage()
    await _seed_graph(fs)
    # Budget large enough for Limits only -> Derivatives excluded from text.
    res = await _recall(fs, budget_counter=lambda t: 1000).run("a", "limit", budget=1000)
    assert "Limits" in res.text_block
    assert "Derivatives" not in res.text_block


async def test_recall_empty_query_returns_empty():
    fs = FakeStorage()
    await _seed_graph(fs)
    res = await _recall(fs).run("a", "   ", budget=800)
    assert res.text_block == ""
    assert res.subgraph == {"nodes": [], "edges": []}
