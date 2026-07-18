"""Keeper closed-vocabulary consolidation + ontology exemptions (Task 6,
host-supplied-ontology design spec 2026-07-15 §6.6, §7 test table).

Dormancy is the key invariant here: a learner with zero external_id nodes
must extract exactly like today (test_no_ontology_nodes_means_open_extraction)
and must still forget/dedupe dynamic nodes normally
(test_non_ontology_node_still_forgotten,
test_repair_merges_still_merges_dynamic_pairs).
"""
import json
from datetime import datetime, timedelta, timezone

from engram.core.engram import Engram
from engram.core.extraction import _SYSTEM
from engram.core.keeper import Keeper
from engram.core.models import LearningEvent, Node, NodeType
from engram.core.ontology import ConceptOntology, OntologyConcept
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _closed(concepts: list[dict]) -> str:
    return json.dumps({"concepts": concepts, "preferences": [], "goals": []})


def _open(concepts: list[dict]) -> str:
    return json.dumps(
        {"concepts": concepts, "preferences": [], "goals": [], "relations": []}
    )


async def _hi(eng: Engram, learner: str = "alice") -> None:
    await eng.ingest([LearningEvent(learner_id=learner, type="utterance", text="hi")])


async def test_vocabulary_built_from_seeded_concepts_only():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_closed([]))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder())
    await eng.seed_ontology(
        "alice", ConceptOntology(concepts=[OntologyConcept(id="c1", label="Slope")])
    )
    # A preference node and a dynamic (non-ontology) concept node must never
    # appear in the catalog sent to the extractor.
    await fs.insert_node(
        Node(learner_id="alice", type=NodeType.PREFERENCE,
             label="bullet points", salience=0.5)
    )
    await fs.insert_node(
        Node(learner_id="alice", type=NodeType.CONCEPT,
             label="Dynamic Concept", salience=0.5, embedding=[0.0, 0.0])
    )
    await _hi(eng)
    await eng.consolidate("alice")

    extractor_calls = [c for c in llm.complete_calls if c[0] == "extractor"]
    assert len(extractor_calls) == 1
    user_content = extractor_calls[0][1][1].content
    assert "c1" in user_content
    assert "bullet points" not in user_content
    assert "Dynamic Concept" not in user_content


async def test_no_ontology_nodes_means_open_extraction():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_open(
        [{"label": "Something New", "summary": "s",
          "evidence": [{"kind": "asked_about", "content": "q"}]}]
    ))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder())
    await _hi(eng)
    report = await eng.consolidate("alice")

    extractor_calls = [c for c in llm.complete_calls if c[0] == "extractor"]
    # main + evidence pass (fix #8) — open mode with >=1 concept; no edge pass
    assert len(extractor_calls) == 2
    assert extractor_calls[0][1][0].content is _SYSTEM
    assert "attribute assessment evidence" in extractor_calls[1][1][0].content
    assert report.nodes_created == 1


async def test_ontology_concept_bypasses_resolve():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_closed([{"concept_id": "c1", "evidence": []}]))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder())
    await eng.seed_ontology(
        "alice", ConceptOntology(concepts=[OntologyConcept(id="c1", label="Slope")])
    )
    await _hi(eng)

    calls: list[int] = []
    orig = Keeper._resolve

    async def _spy(self, *a, **kw):
        calls.append(1)
        return await orig(self, *a, **kw)

    Keeper._resolve = _spy
    try:
        await eng.consolidate("alice")
    finally:
        Keeper._resolve = orig
    assert calls == []


async def test_evidence_lands_on_the_classified_node():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_closed(
        [{"concept_id": "c1",
          "evidence": [{"kind": "quiz_wrong", "content": "got it wrong"}]}]
    ))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder())
    await eng.seed_ontology("alice", ConceptOntology(concepts=[
        OntologyConcept(id="c1", label="Slope"),
        OntologyConcept(id="c2", label="Systems of equations"),
    ]))
    await _hi(eng)
    await eng.consolidate("alice")

    live = {n.external_id: n for n in await fs.get_live_nodes("alice")}
    assert live["c1"].mastery == 0.0  # quiz_wrong -> first obs seeds directly
    assert live["c2"].mastery is None  # untouched


async def test_dropped_concepts_are_audited():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_closed([{"label": "factoring cubics"}]))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder())
    await eng.seed_ontology(
        "alice", ConceptOntology(concepts=[OntologyConcept(id="c1", label="Slope")])
    )
    await _hi(eng)
    await eng.consolidate("alice")

    assert any("factoring cubics" in (a.rationale or "") for a in fs.audit)


async def test_ontology_node_never_forgotten():
    fs = FakeStorage()
    llm = FakeLLM(canned_text=_closed([]))  # c1 is never mentioned -> untouched

    def _future_clock() -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=400)

    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder(), now=_future_clock)
    await eng.seed_ontology(
        "alice", ConceptOntology(concepts=[OntologyConcept(id="c1", label="Slope")])
    )
    await _hi(eng)
    await eng.consolidate("alice")

    node = next(
        n for n in fs.nodes.values()
        if n.learner_id == "alice" and n.external_id == "c1"
    )
    assert node.salience < 0.05  # floored
    assert node.forgotten_at is None  # but never soft-deleted


async def test_non_ontology_node_still_forgotten():
    fs = FakeStorage()
    FIXED = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    stale = await fs.insert_node(Node(
        learner_id="alice", type=NodeType.CONCEPT, label="Old",
        salience=0.06, embedding=[0.0, 1.0],
        last_seen_at=FIXED - timedelta(days=10),  # 0.06*0.98^10 ~= 0.049 < floor
    ))
    llm = FakeLLM(canned_text=_open(
        [{"label": "Fresh", "summary": "s", "evidence": []}]
    ))
    eng = Engram(storage=fs, llm=llm, embedder=FakeEmbedder(), now=lambda: FIXED)
    await _hi(eng)
    await eng.consolidate("alice")

    node = fs.nodes[stale]
    assert node.forgotten_at is not None  # dynamic node still soft-deleted below floor


async def test_repair_merges_skips_ontology_pairs():
    fs = FakeStorage()
    eng = Engram(storage=fs, llm=FakeLLM(canned_text=_closed([])),
                 embedder=FakeEmbedder(dim=4))
    # Same-length labels -> FakeEmbedder gives identical vectors -> cosine 1.0,
    # well above tau_high; without the exemption this pair would merge.
    await eng.seed_ontology("alice", ConceptOntology(concepts=[
        OntologyConcept(id="c1", label="Alpha"),
        OntologyConcept(id="c2", label="Bravo"),
    ]))
    out = await eng.repair_merges("alice")
    assert out["merged"] == 0
    assert len(await fs.get_live_nodes("alice")) == 2


async def test_repair_merges_still_merges_dynamic_pairs():
    fs = FakeStorage()
    await fs.insert_node(Node(
        learner_id="alice", type=NodeType.CONCEPT, label="Newtons First Law",
        salience=0.5, embedding=[1.0, 0.0]))
    await fs.insert_node(Node(
        learner_id="alice", type=NodeType.CONCEPT, label="Photosynthesis Overview",
        salience=0.5, embedding=[1.0, 0.0]))
    eng = Engram(storage=fs, llm=FakeLLM(canned_text=_closed([])),
                 embedder=FakeEmbedder(dim=2))
    out = await eng.repair_merges("alice")
    assert out["merged"] >= 1
