"""Recall hot-path tests (DESIGN §4.4).

Drives the real :func:`engram.core.recall.recall` against ``InMemoryStorage``
with a ``HashingEmbedder`` so vector search is meaningful offline + deterministic.
No network, no database, no LLM reasoning (Recall only embeds the query).
"""

from __future__ import annotations

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    Node,
    NodeType,
)
from engram.core.recall import Recall, recall
from tests.fakes import FakeLLM

DIM = 256


async def _embed(embedder: HashingEmbedder, text: str) -> list[float]:
    return (await embedder.embed([text]))[0]


async def _seed_graph(s: InMemoryStorage, embedder: HashingEmbedder) -> dict[str, str]:
    """Three concept nodes + evidence + one edge for learner ``alice``."""
    deriv = await s.upsert_node(
        Node(
            learner_id="alice",
            type=NodeType.CONCEPT,
            label="derivatives",
            summary="rate of change, slope of a function",
            mastery=0.7,
            confidence=0.6,
            salience=0.9,
            embedding=await _embed(embedder, "derivatives rate of change slope function"),
        )
    )
    limits = await s.upsert_node(
        Node(
            learner_id="alice",
            type=NodeType.CONCEPT,
            label="limits",
            summary="value a function approaches",
            mastery=0.5,
            confidence=0.5,
            salience=0.4,
            embedding=await _embed(embedder, "limits value function approaches epsilon delta"),
        )
    )
    photo = await s.upsert_node(
        Node(
            learner_id="alice",
            type=NodeType.CONCEPT,
            label="photosynthesis",
            summary="plants convert light to energy",
            mastery=0.2,
            confidence=0.3,
            salience=0.8,
            embedding=await _embed(embedder, "photosynthesis plants light energy chlorophyll"),
        )
    )
    # Evidence (importance feeds the score; content feeds the text_block).
    await s.insert_evidence(
        Evidence(
            node_id=deriv,
            kind=EvidenceKind.QUIZ_CORRECT,
            content="solved the chain rule problem",
            importance=0.9,
        )
    )
    await s.insert_evidence(
        Evidence(
            node_id=deriv,
            kind=EvidenceKind.EXPLAINED,
            content="walked through power rule",
            importance=0.6,
        )
    )
    await s.insert_evidence(
        Evidence(
            node_id=limits,
            kind=EvidenceKind.STRUGGLE,
            content="confused by epsilon-delta",
            importance=0.5,
        )
    )
    # limits is a prerequisite of derivatives (1-hop neighbor of the seed).
    await s.upsert_edge(
        Edge(
            learner_id="alice",
            source_id=limits,
            target_id=deriv,
            type=EdgeType.PREREQUISITE,
            weight=1.0,
        )
    )
    return {"derivatives": deriv, "limits": limits, "photosynthesis": photo}


async def test_recall_ranks_most_relevant_first():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    ids = await _seed_graph(s, embedder)
    llm = FakeLLM(embedder=embedder)

    result = await recall(s, llm, "alice", "chain rule derivative slope", budget=600)

    assert result.text_block  # non-empty
    # The most relevant concept ("derivatives") must lead the block.
    first_line = result.text_block.splitlines()[0]
    assert first_line.startswith("- derivatives")
    assert "mastery=0.7" in first_line
    # Off-topic node should not outrank the on-topic ones at the top.
    assert "photosynthesis" not in result.text_block.splitlines()[0]
    # Evidence snippets are rendered under the node line.
    assert "chain rule" in result.text_block

    # subgraph is well-formed + JSON-able-shaped.
    nodes = result.subgraph["nodes"]
    edges = result.subgraph["edges"]
    assert nodes, "expected at least one node"
    n0 = nodes[0]
    assert set(n0) == {
        "id",
        "type",
        "label",
        "mastery",
        "confidence",
        "salience",
        "evidence_count",
    }
    assert n0["type"] == "concept"
    deriv_node = next(n for n in nodes if n["label"] == "derivatives")
    assert deriv_node["evidence_count"] == 2
    # The prerequisite edge is included because both endpoints were selected.
    assert ids["derivatives"] in {n["id"] for n in nodes}
    if edges:
        e0 = edges[0]
        assert set(e0) == {"id", "source", "target", "type", "weight"}
        assert e0["type"] == "prerequisite"


async def test_recall_includes_edge_between_selected_nodes():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    ids = await _seed_graph(s, embedder)
    llm = FakeLLM(embedder=embedder)

    # A query touching both limits and derivatives so both get selected.
    result = await recall(
        s, llm, "alice", "limits and derivatives slope function approaches", budget=600
    )
    selected_ids = {n["id"] for n in result.subgraph["nodes"]}
    # Both endpoints present -> the prerequisite edge must appear.
    if ids["limits"] in selected_ids and ids["derivatives"] in selected_ids:
        assert any(
            e["source"] == ids["limits"] and e["target"] == ids["derivatives"]
            for e in result.subgraph["edges"]
        )


async def test_recall_respects_tiny_token_budget():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    await _seed_graph(s, embedder)
    llm = FakeLLM(embedder=embedder)

    tiny = await recall(s, llm, "alice", "derivatives slope", budget=10)
    big = await recall(s, llm, "alice", "derivatives slope", budget=600)

    # A tiny budget yields a strictly shorter (or equal) block and at most ~one node.
    assert len(tiny.text_block) <= len(big.text_block)
    assert len(tiny.subgraph["nodes"]) <= len(big.subgraph["nodes"])
    # At least one node is always emitted (we keep one even if it overflows).
    assert len(tiny.subgraph["nodes"]) >= 1
    # The tiny block should be a single node's worth of lines (no second node line).
    node_lines = [ln for ln in tiny.text_block.splitlines() if ln.startswith("- ")]
    assert len(node_lines) == 1


async def test_recall_empty_graph_returns_empty():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    llm = FakeLLM(embedder=embedder)

    result = await recall(s, llm, "nobody", "anything", budget=600)
    assert result.text_block == ""
    assert result.subgraph == {"nodes": [], "edges": []}


async def test_recall_writes_best_effort_audit():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    await _seed_graph(s, embedder)
    llm = FakeLLM(embedder=embedder)

    await recall(s, llm, "alice", "derivatives", budget=600)
    audit = await s.get_audit("alice")
    assert any(a.op == "recall" for a in audit)


async def test_recall_weights_overridable_per_call():
    embedder = HashingEmbedder(DIM)
    s = InMemoryStorage()
    await _seed_graph(s, embedder)
    llm = FakeLLM(embedder=embedder)

    r = Recall(weights={"recency": 1.0, "importance": 0.0, "relevance": 0.0})
    # Pure-recency weighting -> highest-salience node ("derivatives", 0.9) leads.
    result = await r.recall(s, llm, "alice", "derivatives", budget=600)
    assert result.text_block.splitlines()[0].startswith("- derivatives")
