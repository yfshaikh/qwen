import uuid

from engram.adapters.storage.postgres import PostgresStorage
from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)


def _vec(*nonzero_first):
    # 1024-dim vector with the given leading values, rest zeros.
    v = [0.0] * 1024
    for i, x in enumerate(nonzero_first):
        v[i] = float(x)
    return v


async def test_health_false_before_connect(database_url):
    storage = PostgresStorage(database_url)
    assert await storage.health() is False


async def test_event_insert_round_trip(database_url):
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        ids = await storage.insert_events(
            [
                LearningEvent(learner_id=learner, type="utterance", text="hi",
                              refs={"doc": 1}, signals={"correct": True}),
                LearningEvent(learner_id=learner, type="note", text="n"),
            ]
        )
        assert len(ids) == 2
    finally:
        await storage.close()


async def test_node_edge_evidence_and_reads(database_url):
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        a = await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="A",
                 summary="alpha", mastery=0.7, salience=0.9, embedding=_vec(1, 0))
        )
        b = await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="B",
                 salience=0.5, embedding=_vec(0, 1))
        )
        await storage.insert_edge(
            Edge(learner_id=learner, source_id=a, target_id=b,
                 type=EdgeType.PREREQUISITE)
        )
        await storage.insert_evidence(
            Evidence(node_id=a, kind=EvidenceKind.QUIZ_CORRECT, content="ok",
                     importance=0.8, embedding=_vec(1, 0))
        )

        seeds = await storage.vector_search(learner, _vec(1, 0), k=1)
        assert len(seeds) == 1 and seeds[0].label == "A"
        assert seeds[0].embedding is not None and len(seeds[0].embedding) == 1024

        edges = await storage.get_edges(learner, [a])
        assert len(edges) == 1 and edges[0].target_id == b

        nodes = await storage.get_nodes(learner, [b])
        assert [n.label for n in nodes] == ["B"]

        ev = await storage.top_evidence([a], per_node=2)
        assert ev[a][0].content == "ok"
    finally:
        await storage.close()


async def test_vector_search_excludes_forgotten(database_url):
    from datetime import datetime, timezone

    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="Gone",
                 embedding=_vec(1, 0), forgotten_at=datetime.now(timezone.utc))
        )
        await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="Here",
                 embedding=_vec(1, 0))
        )
        seeds = await storage.vector_search(learner, _vec(1, 0), k=5)
        assert [n.label for n in seeds] == ["Here"]
    finally:
        await storage.close()


async def test_get_all_nodes_includes_forgotten(database_url):
    from datetime import datetime, timezone

    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="Live",
                 embedding=_vec(1, 0))
        )
        await storage.insert_node(
            Node(learner_id=learner, type=NodeType.CONCEPT, label="Dead",
                 embedding=_vec(1, 0), forgotten_at=datetime.now(timezone.utc))
        )
        live = await storage.get_live_nodes(learner)
        assert [n.label for n in live] == ["Live"]

        allnodes = await storage.get_all_nodes(learner)
        assert {n.label for n in allnodes} == {"Live", "Dead"}
    finally:
        await storage.close()
