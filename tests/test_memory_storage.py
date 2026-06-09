"""Round-trip coverage for InMemoryStorage — the contract the Postgres adapter
must match, and the substrate every logic test runs on."""

from datetime import datetime, timedelta, timezone

from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import (
    AuditEntry,
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)


async def test_event_lifecycle():
    s = InMemoryStorage()
    eid = await s.insert_event(LearningEvent(learner_id="a", type="utterance", text="hi"))
    assert await s.count_pending_events("a") == 1
    pending = await s.fetch_unconsolidated_events("a")
    assert len(pending) == 1 and pending[0].id == eid
    await s.mark_events_consolidated([eid])
    assert await s.count_pending_events("a") == 0


async def test_returned_objects_are_copies():
    s = InMemoryStorage()
    await s.insert_event(LearningEvent(learner_id="a", type="note", text="x"))
    ev = (await s.fetch_unconsolidated_events("a"))[0]
    ev.text = "mutated"
    assert (await s.fetch_unconsolidated_events("a"))[0].text == "x"


async def test_node_upsert_get_filter():
    s = InMemoryStorage()
    nid = await s.upsert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="derivatives"))
    got = await s.get_node(nid)
    assert got is not None and got.label == "derivatives"

    await s.upsert_node(Node(learner_id="a", type=NodeType.GOAL, label="pass calc"))
    concepts = await s.get_nodes("a", types=["concept"])
    assert [n.label for n in concepts] == ["derivatives"]

    await s.update_node_state(nid, forgotten_at=datetime.now(timezone.utc))
    assert await s.get_nodes("a", types=["concept"]) == []
    assert len(await s.get_nodes("a", types=["concept"], include_forgotten=True)) == 1


async def test_vector_search_orders_by_similarity():
    s = InMemoryStorage()
    await s.upsert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="near", embedding=[1.0, 0.0, 0.0]))
    await s.upsert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="mid", embedding=[0.7, 0.7, 0.0]))
    await s.upsert_node(Node(learner_id="a", type=NodeType.CONCEPT, label="far", embedding=[0.0, 0.0, 1.0]))
    hits = await s.vector_search("a", [1.0, 0.0, 0.0], k=3)
    assert [n.label for n, _ in hits] == ["near", "mid", "far"]
    assert hits[0][1] > hits[-1][1]


async def test_edges_dedupe_and_filter():
    s = InMemoryStorage()
    e1 = await s.upsert_edge(Edge(learner_id="a", source_id="n1", target_id="n2", type=EdgeType.PREREQUISITE))
    e2 = await s.upsert_edge(Edge(learner_id="a", source_id="n1", target_id="n2", type=EdgeType.PREREQUISITE, weight=2.0))
    assert e1 == e2  # deduped
    edges = await s.get_edges("a", node_ids=["n1"])
    assert len(edges) == 1 and edges[0].weight == 2.0
    assert await s.get_edges("a", node_ids=["n9"]) == []


async def test_evidence_and_counts():
    s = InMemoryStorage()
    await s.insert_evidence(Evidence(node_id="n1", kind=EvidenceKind.STRUGGLE, content="missed Q3"))
    await s.insert_evidence(Evidence(node_id="n1", kind=EvidenceKind.QUIZ_CORRECT, content="got Q4"))
    assert len(await s.get_evidence("n1")) == 2
    assert await s.evidence_counts(["n1", "n2"]) == {"n1": 2, "n2": 0}


async def test_audit_and_mastery_history():
    s = InMemoryStorage()
    await s.insert_audit(AuditEntry(learner_id="a", op="extract", rationale="r1"))
    await s.insert_audit(AuditEntry(learner_id="a", op="recall", rationale="r2"))
    audit = await s.get_audit("a")
    assert {a.op for a in audit} == {"extract", "recall"}

    await s.insert_mastery_snapshot("n1", 0.4, 0.5)
    await s.insert_mastery_snapshot("n1", 0.6, 0.7)
    hist = await s.get_mastery_history("n1")
    assert [m for _, m, _ in hist] == [0.4, 0.6]


async def test_learners_with_pending_events_quiet_filter():
    s = InMemoryStorage()
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    await s.insert_event(LearningEvent(learner_id="quiet", type="utterance", ts=old))
    await s.insert_event(LearningEvent(learner_id="active", type="utterance"))
    quiet = await s.learners_with_pending_events(quiet_for_seconds=120)
    assert quiet == ["quiet"]
    assert set(await s.learners_with_pending_events(0)) == {"quiet", "active"}
