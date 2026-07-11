"""Keeper.repair_merges collapses pre-existing duplicates in place (#6 layer 3)."""
from datetime import datetime, timedelta, timezone

from engram.core.engram import Engram
from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Node, NodeType
from tests.fakes import FakeEmbedder, FakeStorage


class _NoLLM:
    async def complete(self, role, messages, schema=None):
        from engram.core.models import Completion
        return Completion(text="no")


def _t(days: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=days)


async def _graph_with_dups():
    # One-hot embeddings on distinct axes: every cross-node cosine is 0.0, so
    # ONLY the lexical path may merge (and "Magnetic Flux" can never be pulled in).
    storage = FakeStorage()
    old = await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="NMOS Transistor",
        mastery=0.8, confidence=0.9, salience=0.6, importance=0.5,
        embedding=[1.0, 0.0, 0.0], created_at=_t(0)))
    new = await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="nmos transistors",
        mastery=0.2, confidence=0.3, salience=0.9, importance=0.8,
        embedding=[0.0, 1.0, 0.0], created_at=_t(5)))
    other = await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Magnetic Flux",
        mastery=0.5, confidence=0.5, salience=0.5,
        embedding=[0.0, 0.0, 1.0], created_at=_t(1)))
    await storage.insert_edge(Edge(learner_id="L", source_id=new, target_id=other,
                                   type=EdgeType.RELATES_TO))
    await storage.insert_edge(Edge(learner_id="L", source_id=new, target_id=old,
                                   type=EdgeType.RELATES_TO))
    await storage.insert_evidence(Evidence(node_id=new, kind=EvidenceKind.NOTE,
                                           content="evidence on the dup"))
    return storage, old, new, other


async def test_repair_merges_lexical_duplicates():
    storage, old, new, other = await _graph_with_dups()
    eng = Engram(storage=storage, llm=_NoLLM(), embedder=FakeEmbedder(dim=2))
    out = await eng.repair_merges("L")
    assert out["merged"] == 1
    live = await storage.get_live_nodes("L")
    labels = sorted(n.label for n in live)
    assert labels == ["Magnetic Flux", "NMOS Transistor"]  # older node id kept
    keep = next(n for n in live if n.label == "NMOS Transistor")
    assert keep.id == old
    # mastery from the higher-confidence node; confidence/salience/importance = max
    assert keep.mastery == 0.8 and keep.confidence == 0.9
    assert keep.salience == 0.9 and keep.importance == 0.8
    # evidence repointed; edge repointed; self-loop dropped
    assert any(ev.node_id == old for ev in storage.evidence)
    live_edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(live_edges) == 1
    assert {live_edges[0].source_id, live_edges[0].target_id} == {old, other}
    ops = [a["op"] for a in await storage.get_audit("L")]
    assert "merge" in ops


async def test_repair_keeps_distinct_similar_sounding_concepts():
    storage = FakeStorage()
    # distinct concepts, orthogonal embeddings, low jaccard -> must survive
    for label, emb in (("Electric Field", [1.0, 0.0]), ("Magnetic Field", [0.0, 1.0])):
        await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT,
                                       label=label, salience=0.5, embedding=emb))
    eng = Engram(storage=storage, llm=_NoLLM(), embedder=FakeEmbedder(dim=2))
    out = await eng.repair_merges("L")
    assert out["merged"] == 0
    assert len(await storage.get_live_nodes("L")) == 2


async def test_repair_never_merges_across_node_types():
    storage = FakeStorage()
    await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT,
                                   label="Exam", salience=0.5, embedding=[1.0, 0.0]))
    await storage.insert_node(Node(learner_id="L", type=NodeType.GOAL,
                                   label="Exam", salience=0.5, embedding=[1.0, 0.0]))
    eng = Engram(storage=storage, llm=_NoLLM(), embedder=FakeEmbedder(dim=2))
    out = await eng.repair_merges("L")
    assert out["merged"] == 0


async def test_repair_reflector_no_is_not_reasked():
    """Rejected mid-band pairs must not re-hit the reflector on later passes."""
    storage = FakeStorage()
    # Orthogonal axes would give cos=0; use identical embeddings so cos=1.0
    # sits above tau_high — force mid-band with near-parallel but mid-tau vectors.
    # Use tau defaults: tau_low=0.72, tau_high=0.86. Cosine of [1,0] and [0.8,0.6]:
    # 0.8 — mid-band.
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Alpha Thing",
        salience=0.5, embedding=[1.0, 0.0], created_at=_t(0)))
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Beta Widget",
        salience=0.5, embedding=[0.8, 0.6], created_at=_t(1)))

    class _CountingNo:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, messages, schema=None):
            from engram.core.models import Completion
            if role == "reflector":
                self.calls += 1
            return Completion(text="no")

    llm = _CountingNo()
    eng = Engram(storage=storage, llm=llm, embedder=FakeEmbedder(dim=2))
    out = await eng.repair_merges("L")
    assert out["merged"] == 0
    assert llm.calls == 1  # asked once, not re-asked on the next while-pass
