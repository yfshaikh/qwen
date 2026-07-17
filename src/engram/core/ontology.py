"""Host-supplied curriculum: concepts and the dependencies between them.

An ontology is the HOST's curriculum, not Engram's inference. Seeding a learner
from one flips the extractor from inventing concepts to classifying into a fixed
vocabulary, and stops it inferring relations entirely — every edge comes from
here. See docs/superpowers/specs/2026-07-15-host-supplied-ontology-design.md.

This module is pure: no I/O, no LLM, no storage. It defines the type, validates
it, and builds the Node/Edge objects the facade hands to storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engram.core.models import Edge, EdgeType, Node, NodeType


class OntologyError(ValueError):
    """The host handed us a curriculum that cannot be seeded.

    Raised at the trust boundary, never swallowed. A malformed ontology seeded
    anyway would corrupt every downstream graph walk silently; failing loudly at
    the one call site that has the host's stack trace is worth more than any
    partial seed.
    """


@dataclass(slots=True)
class OntologyConcept:
    """One curriculum concept.

    `id` is the HOST's stable key and is opaque to Engram — Marfini passes its
    concept UUID, the SAT site passes the label itself. It lands on
    `Node.external_id` and is what a host joins its own tables back on.
    """

    id: str
    label: str
    summary: str | None = None


@dataclass(slots=True)
class OntologyEdge:
    """A curriculum relation between two OntologyConcept ids.

    Direction is Engram's, not the host's: `source` is the thing taught FIRST
    (the prerequisite, or the part), `target` is the thing that depends on it
    (the dependent, or the whole). Hosts whose own storage records the inverse
    must flip on the way in — see §5, Marfini does exactly this.
    """

    source: str
    target: str
    type: EdgeType = EdgeType.PREREQUISITE


@dataclass(slots=True)
class ConceptOntology:
    concepts: list[OntologyConcept]
    edges: list[OntologyEdge] = field(default_factory=list)

    def validate(self) -> None:
        """Raise OntologyError unless this is seedable. Called by seed_ontology
        before anything is embedded or written."""
        if not self.concepts:
            raise OntologyError("ontology has no concepts")

        seen: set[str] = set()
        for c in self.concepts:
            if not c.id or not c.id.strip():
                raise OntologyError(f"concept {c.label!r} has an empty id")
            if not c.label or not c.label.strip():
                raise OntologyError(f"concept id {c.id!r} has an empty label")
            if c.id in seen:
                raise OntologyError(f"duplicate concept id {c.id!r}")
            seen.add(c.id)

        # One edge per UNDIRECTED pair, regardless of type. This is not a
        # stylistic choice — migration 0004 puts a unique index on
        # (learner_id, LEAST(source,target), GREATEST(source,target)), so a
        # second edge on the same pair is a UniqueViolationError at seed time.
        # Catching it here turns a mid-transaction DB explosion into a clean
        # OntologyError at the boundary, with the host's stack. It also means
        # `A --prereq--> B` and `B --part_of--> A` cannot coexist: pick one
        # relationship between two concepts.
        pairs: set[frozenset[str]] = set()
        for e in self.edges:
            if e.source not in seen:
                raise OntologyError(f"edge source {e.source!r} is not a concept id")
            if e.target not in seen:
                raise OntologyError(f"edge target {e.target!r} is not a concept id")
            if e.source == e.target:
                raise OntologyError(f"self-edge on {e.source!r}")
            pair = frozenset((e.source, e.target))
            if pair in pairs:
                raise OntologyError(
                    f"two edges between {e.source!r} and {e.target!r}; "
                    "one relationship per concept pair")
            pairs.add(pair)

        # Acyclic PER EDGE TYPE, not over the union. A prerequisite cycle makes
        # "what must I learn first" unanswerable and would hang or mislead a
        # prereq walk; the same is true of a part_of walk. But a MIXED-type
        # directed cycle (A --prereq--> B --prereq--> C --part_of--> A) traps no
        # real walk, because every walk follows a single edge type — so checking
        # the union would reject valid curricula. Undirected-pair uniqueness
        # above already means each type's subgraph is a simple directed graph.
        for edge_type in {e.type for e in self.edges}:
            _assert_acyclic([e for e in self.edges if e.type is edge_type], edge_type)


def _assert_acyclic(edges: list[OntologyEdge], edge_type: EdgeType) -> None:
    """Iterative DFS with a three-colour marking. Iterative, not recursive: a
    deep curriculum chain would blow Python's 1000-frame default."""
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e.source, []).append(e.target)

    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}

    for root in list(adj):
        if colour.get(root, WHITE) != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        colour[root] = GREY
        while stack:
            node, i = stack[-1]
            if i < len(adj.get(node, [])):
                stack[-1] = (node, i + 1)
                nxt = adj[node][i]
                c = colour.get(nxt, WHITE)
                if c == GREY:
                    raise OntologyError(
                        f"{edge_type.value} cycle through {nxt!r}"
                    )
                if c == WHITE:
                    colour[nxt] = GREY
                    stack.append((nxt, 0))
            else:
                colour[node] = BLACK
                stack.pop()


def embed_texts(ontology: ConceptOntology) -> list[str]:
    """The strings to embed, in `ontology.concepts` order. Mirrors
    ExtractedNode.embed_text() so seeded vectors and extracted vectors share a
    space."""
    return [
        c.label + (f" {c.summary}" if c.summary else "") for c in ontology.concepts
    ]


def build_seed_nodes(
    learner_id: str, ontology: ConceptOntology, vectors: list[list[float]]
) -> list[Node]:
    """Nodes for every ontology concept, in order, `id=None`.

    A seeded node is a curriculum fact the learner has no relationship with yet:
    mastery None ("never assessed" — distinct from 0.0, "assessed and got it
    wrong"), confidence and salience 0.0 (recall must not surface a topic they
    have never touched), importance None (recall's neutral 0.3 prior applies).
    """
    return [
        Node(
            learner_id=learner_id,
            type=NodeType.CONCEPT,
            label=c.label,
            summary=c.summary,
            external_id=c.id,
            mastery=None,
            confidence=0.0,
            salience=0.0,
            importance=None,
            embedding=list(vec),
        )
        for c, vec in zip(ontology.concepts, vectors)
    ]


def build_seed_edges(learner_id: str, ontology: ConceptOntology) -> list[Edge]:
    """Edges whose source_id/target_id are EXTERNAL ids, not node ids.

    Node ids do not exist until the adapter has written the nodes, so the
    adapter resolves these — see StoragePort.apply_ontology's contract in §6.
    """
    return [
        Edge(
            learner_id=learner_id,
            source_id=e.source,
            target_id=e.target,
            type=e.type,
        )
        for e in ontology.edges
    ]
