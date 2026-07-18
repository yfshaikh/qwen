import pytest
from engram.core.models import EdgeType, NodeType
from engram.core.ontology import (
    ConceptOntology,
    OntologyConcept,
    OntologyEdge,
    OntologyError,
    build_seed_edges,
    build_seed_nodes,
    embed_texts,  # noqa: F401 -- imported to assert the symbol exists per the module's interface
)


def _marfini() -> ConceptOntology:
    return ConceptOntology(
        concepts=[
            OntologyConcept(id="u1", label="Slope", summary="rise over run"),
            OntologyConcept(id="u2", label="Slope-intercept form"),
            OntologyConcept(id="u3", label="Systems of equations"),
        ],
        edges=[
            OntologyEdge("u1", "u2", EdgeType.PREREQUISITE),
            OntologyEdge("u2", "u3", EdgeType.PREREQUISITE),
        ],
    )


def _sat() -> ConceptOntology:
    return ConceptOntology(
        concepts=[
            OntologyConcept(id="Algebra", label="Algebra"),
            OntologyConcept(id="Linear functions", label="Linear functions"),
        ],
        edges=[OntologyEdge("Linear functions", "Algebra", EdgeType.PART_OF)],
    )


def test_validate_accepts_marfini_shape():
    _marfini().validate()  # no raise


def test_validate_accepts_sat_shape():
    _sat().validate()  # no raise


def test_empty_ontology_rejected():
    with pytest.raises(OntologyError, match="concept"):
        ConceptOntology(concepts=[]).validate()


def test_duplicate_concept_id_rejected():
    o = ConceptOntology(concepts=[
        OntologyConcept(id="x", label="A"),
        OntologyConcept(id="x", label="B"),
    ])
    with pytest.raises(OntologyError, match="x"):
        o.validate()


def test_empty_id_or_label_rejected():
    with pytest.raises(OntologyError):
        ConceptOntology(concepts=[OntologyConcept(id="", label="A")]).validate()
    with pytest.raises(OntologyError):
        ConceptOntology(concepts=[OntologyConcept(id="a", label="  ")]).validate()


def test_unknown_edge_endpoint_rejected():
    o = ConceptOntology(
        concepts=[OntologyConcept(id="a", label="A")],
        edges=[OntologyEdge("a", "ghost", EdgeType.PREREQUISITE)],
    )
    with pytest.raises(OntologyError, match="ghost"):
        o.validate()


def test_self_edge_rejected():
    o = ConceptOntology(
        concepts=[OntologyConcept(id="a", label="A")],
        edges=[OntologyEdge("a", "a", EdgeType.PREREQUISITE)],
    )
    with pytest.raises(OntologyError, match="self-edge"):
        o.validate()


def test_prerequisite_cycle_rejected():
    o = ConceptOntology(
        concepts=[OntologyConcept(id=x, label=x) for x in ("a", "b", "c")],
        edges=[
            OntologyEdge("a", "b", EdgeType.PREREQUISITE),
            OntologyEdge("b", "c", EdgeType.PREREQUISITE),
            OntologyEdge("c", "a", EdgeType.PREREQUISITE),
        ],
    )
    with pytest.raises(OntologyError, match="prerequisite"):
        o.validate()


def test_duplicate_undirected_pair_rejected():
    # A--prereq-->B plus B--part_of-->A is the SAME undirected pair {A,B};
    # migration 0004's unique index forbids it, so validate must too.
    o = ConceptOntology(
        concepts=[OntologyConcept(id="a", label="A"), OntologyConcept(id="b", label="B")],
        edges=[
            OntologyEdge("a", "b", EdgeType.PREREQUISITE),
            OntologyEdge("b", "a", EdgeType.PART_OF),
        ],
    )
    with pytest.raises(OntologyError, match="one relationship"):
        o.validate()


def test_mixed_type_cycle_allowed():
    # Distinct undirected pairs; a directed cycle only across types. No single-
    # type walk ever sees a cycle, so this is valid.
    o = ConceptOntology(
        concepts=[OntologyConcept(id=x, label=x) for x in ("a", "b", "c")],
        edges=[
            OntologyEdge("a", "b", EdgeType.PREREQUISITE),
            OntologyEdge("b", "c", EdgeType.PREREQUISITE),
            OntologyEdge("c", "a", EdgeType.PART_OF),
        ],
    )
    o.validate()  # no raise


def test_deep_chain_does_not_recurse():
    n = 2000
    concepts = [OntologyConcept(id=str(i), label=str(i)) for i in range(n)]
    edges = [OntologyEdge(str(i), str(i + 1), EdgeType.PREREQUISITE) for i in range(n - 1)]
    ConceptOntology(concepts=concepts, edges=edges).validate()  # no RecursionError


def test_seed_nodes_have_no_learner_relationship():
    o = _marfini()
    vecs = [[0.1, 0.2]] * len(o.concepts)
    nodes = build_seed_nodes("alice", o, vecs)
    assert len(nodes) == 3
    n = nodes[0]
    assert n.mastery is None and n.confidence == 0.0 and n.salience == 0.0
    assert n.importance is None
    assert n.external_id == "u1" and n.type is NodeType.CONCEPT
    assert n.label == "Slope" and n.summary == "rise over run"


def test_seed_edges_carry_external_ids():
    edges = build_seed_edges("alice", _marfini())
    assert (edges[0].source_id, edges[0].target_id) == ("u1", "u2")
    assert edges[0].type is EdgeType.PREREQUISITE


# --- string coercion at the boundary (Marfini seed bug, 2026-07-18) ---------
# EdgeType subclasses str, so type="prerequisite" used to construct fine, pass
# validate(), and die at the first `.type.value` — deep inside the seed write,
# swallowed by the host's fire-and-forget reaper. Every session "seeded" and
# seeded nothing. __post_init__ coercion turns the whole class of bug into
# either a working seed or a ValueError in the host's own stack.

def test_edge_type_string_is_coerced_to_enum():
    e = OntologyEdge("a", "b", "part_of")
    assert e.type is EdgeType.PART_OF


def test_edge_type_junk_string_raises_at_construction():
    with pytest.raises(ValueError):
        OntologyEdge("a", "b", "prereq")


def test_string_typed_ontology_seeds_enum_typed_edges():
    # the exact Marfini shape: plain-string edge types end to end
    ont = ConceptOntology(
        concepts=[OntologyConcept(id="a", label="A"), OntologyConcept(id="b", label="B")],
        edges=[OntologyEdge(source="a", target="b", type="prerequisite")],
    )
    ont.validate()
    edges = build_seed_edges("L", ont)
    assert edges[0].type is EdgeType.PREREQUISITE
    assert edges[0].type.value == "prerequisite"  # the exact call that crashed
