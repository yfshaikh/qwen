"""Recall — deterministic tests on InMemoryStorage + HashingEmbedder (no network)."""

from __future__ import annotations

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Node, NodeType
from engram.core.recall import recall
from tests.fakes import FakeLLM

DIM = 256


async def _seeded() -> tuple[InMemoryStorage, FakeLLM, dict[str, str]]:
    """Three concepts (one clearly relevant to 'derivatives'), evidence, an edge."""
    emb = HashingEmbedder(DIM)
    storage = InMemoryStorage()
    llm = FakeLLM(embedder=emb)

    ids: dict[str, str] = {}
    for label, summary, salience, mastery in [
        ("derivatives", "rate of change; chain rule trouble", 0.9, 0.4),
        ("limits", "epsilon-delta definitions", 0.5, 0.7),
        ("photosynthesis", "plants turning light into sugar", 0.5, 0.9),
    ]:
        vec = (await emb.embed([f"{label} {summary}"]))[0]
        ids[label] = await storage.upsert_node(
            Node(
                learner_id="alice",
                type=NodeType.CONCEPT,
                label=label,
                summary=summary,
                mastery=mastery,
                salience=salience,
                embedding=vec,
            )
        )
    await storage.insert_evidence(
        Evidence(
            node_id=ids["derivatives"],
            kind=EvidenceKind.STRUGGLE,
            content="missed the chain rule question",
            importance=0.8,
        )
    )
    await storage.upsert_edge(
        Edge(
            learner_id="alice",
            source_id=ids["derivatives"],
            target_id=ids["limits"],
            type=EdgeType.PREREQUISITE,
        )
    )
    return storage, llm, ids


async def test_most_relevant_node_leads_the_block():
    storage, llm, _ = await _seeded()
    result = await recall(storage, llm, "alice", "help with derivatives and the chain rule")
    assert result.text_block.splitlines()[0].startswith("- derivatives")
    assert "chain rule" in result.text_block  # evidence snippet included
    labels = [n["label"] for n in result.subgraph["nodes"]]
    assert "derivatives" in labels


async def test_one_hop_neighbors_and_edges_included():
    storage, llm, ids = await _seeded()
    result = await recall(storage, llm, "alice", "derivatives", budget=600)
    labels = {n["label"] for n in result.subgraph["nodes"]}
    assert {"derivatives", "limits"} <= labels  # neighbor pulled in via the edge
    edge_pairs = {(e["source"], e["target"]) for e in result.subgraph["edges"]}
    assert (ids["derivatives"], ids["limits"]) in edge_pairs


async def test_budget_limits_output():
    storage, llm, _ = await _seeded()
    small = await recall(storage, llm, "alice", "derivatives", budget=15)
    large = await recall(storage, llm, "alice", "derivatives", budget=2000)
    assert len(small.subgraph["nodes"]) <= len(large.subgraph["nodes"])
    assert len(small.text_block) < len(large.text_block)
    assert len(small.subgraph["nodes"]) >= 1  # at least one node even on tiny budgets


async def test_empty_graph_returns_empty_result():
    storage, llm = InMemoryStorage(), FakeLLM(embedder=HashingEmbedder(DIM))
    result = await recall(storage, llm, "nobody", "anything")
    assert result.text_block == ""
    assert result.subgraph == {"nodes": [], "edges": []}


async def test_recall_writes_audit_row():
    storage, llm, _ = await _seeded()
    await recall(storage, llm, "alice", "derivatives")
    ops = [a.op for a in await storage.get_audit("alice")]
    assert "recall" in ops


async def test_node_dicts_are_well_formed():
    storage, llm, _ = await _seeded()
    result = await recall(storage, llm, "alice", "derivatives")
    for n in result.subgraph["nodes"]:
        assert set(n) == {
            "id", "type", "label", "mastery", "confidence", "salience", "evidence_count",
        }
    for e in result.subgraph["edges"]:
        assert set(e) == {"id", "source", "target", "type", "weight"}
