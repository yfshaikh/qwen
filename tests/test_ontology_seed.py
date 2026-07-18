import pytest
from engram.core.engram import Engram
from engram.core.models import EdgeType
from engram.core.ontology import ConceptOntology, OntologyConcept, OntologyEdge, OntologyError
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _eng() -> Engram:
    return Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder())


def _ont() -> ConceptOntology:
    return ConceptOntology(
        concepts=[
            OntologyConcept(id="u1", label="Slope"),
            OntologyConcept(id="u2", label="Slope-intercept form"),
        ],
        edges=[OntologyEdge("u1", "u2", EdgeType.PREREQUISITE)],
    )


async def _live(eng, learner):
    return await eng.storage.get_live_nodes(learner)


async def test_seed_creates_nodes_and_edges():
    eng = _eng()
    res = await eng.seed_ontology("alice", _ont())
    assert res == {"inserted": 2, "updated": 0, "edges": 1}
    assert len(await _live(eng, "alice")) == 2


async def test_reseed_is_idempotent():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())
    res = await eng.seed_ontology("alice", _ont())
    assert res["inserted"] == 0 and res["updated"] == 2
    assert len(await _live(eng, "alice")) == 2


async def test_reseed_preserves_mastery():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())
    slope = next(n for n in await _live(eng, "alice") if n.external_id == "u1")
    slope.mastery = 0.8
    await eng.seed_ontology("alice", _ont())
    slope2 = next(n for n in await _live(eng, "alice") if n.external_id == "u1")
    assert slope2.mastery == 0.8


async def test_reseed_refreshes_label():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())
    renamed = ConceptOntology(
        concepts=[OntologyConcept(id="u1", label="Gradient"),
                  OntologyConcept(id="u2", label="Slope-intercept form")],
        edges=[OntologyEdge("u1", "u2", EdgeType.PREREQUISITE)],
    )
    await eng.seed_ontology("alice", renamed)
    labels = {n.external_id: n.label for n in await _live(eng, "alice")}
    assert labels["u1"] == "Gradient"


async def test_reseed_replaces_edges():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())
    flipped = ConceptOntology(
        concepts=[OntologyConcept(id="u1", label="Slope"),
                  OntologyConcept(id="u2", label="Slope-intercept form")],
        edges=[OntologyEdge("u2", "u1", EdgeType.PREREQUISITE)],
    )
    await eng.seed_ontology("alice", flipped)
    ids = {n.external_id: n.id for n in await _live(eng, "alice")}
    edges = await eng.storage.get_edges("alice", list(ids.values()))
    assert len(edges) == 1
    assert edges[0].source_id == ids["u2"] and edges[0].target_id == ids["u1"]


async def test_reseed_keeps_concepts_dropped_from_curriculum():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())
    smaller = ConceptOntology(concepts=[OntologyConcept(id="u1", label="Slope")])
    await eng.seed_ontology("alice", smaller)
    ext = {n.external_id for n in await _live(eng, "alice")}
    assert ext == {"u1", "u2"}  # u2 kept, not deleted


async def test_seed_two_ontologies_composes():
    eng = _eng()
    await eng.seed_ontology("alice", _ont())          # u1 --prereq--> u2
    # The second ontology carries its OWN edge: seeding it must not wipe the
    # first's. (An edge-less second ontology would hide that bug — the first
    # curriculum's edges get deleted and nobody notices.)
    other = ConceptOntology(
        concepts=[OntologyConcept(id="r1", label="Reading"),
                  OntologyConcept(id="r2", label="Inference")],
        edges=[OntologyEdge("r1", "r2", EdgeType.PART_OF)],
    )
    await eng.seed_ontology("alice", other)
    ids = {n.external_id: n.id for n in await _live(eng, "alice")}
    assert len(ids) == 4
    edges = await eng.storage.get_edges("alice", list(ids.values()))
    pairs = {(e.source_id, e.target_id, e.type) for e in edges}
    assert (ids["u1"], ids["u2"], EdgeType.PREREQUISITE) in pairs  # survived
    assert (ids["r1"], ids["r2"], EdgeType.PART_OF) in pairs       # added
    assert len(edges) == 2


async def test_invalid_ontology_writes_nothing():
    eng = _eng()
    bad = ConceptOntology(concepts=[])
    with pytest.raises(OntologyError):
        await eng.seed_ontology("alice", bad)
    assert await _live(eng, "alice") == []
    assert len(eng.embedder.embed_calls) == 0  # validation ran before any embed
