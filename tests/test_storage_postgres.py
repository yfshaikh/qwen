"""Live tests against the docker-compose pgvector container.

Bring it up first: `docker compose up -d db`. The whole module skips gracefully
if the database is unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from engram.adapters.storage.postgres import PostgresStorage
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


def _learner() -> str:
    return f"test-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _embedding(*hot: int) -> list[float]:
    vec = [0.0] * 1024
    for i in hot:
        vec[i] = 1.0
    return vec


@pytest.fixture
async def storage(database_url: str) -> AsyncIterator[PostgresStorage]:
    s = PostgresStorage(database_url)
    try:
        await s.connect()
    except Exception:
        pytest.skip("live Postgres not reachable")
    if not await s.health():
        await s.close()
        pytest.skip("live Postgres not healthy")
    yield s
    await s.close()


# --- Health ---


async def test_health_true_against_live_db(storage: PostgresStorage) -> None:
    assert await storage.health() is True


async def test_health_false_when_db_unreachable() -> None:
    # Unused port; connection must fail fast and health() must return False.
    s = PostgresStorage("postgresql://engram:engram@127.0.0.1:1/engram")
    # connect() may itself raise — that's fine; health() is the contract.
    try:
        await s.connect()
    except Exception:
        pass
    assert await s.health() is False


# --- Events ---


async def test_event_lifecycle(storage: PostgresStorage) -> None:
    lid = _learner()
    t0 = _now()
    e1 = LearningEvent(
        learner_id=lid,
        type="utterance",
        text="what is a derivative?",
        refs={"session": "s1"},
        signals={"hesitation": 0.2},
        ts=t0 - timedelta(seconds=30),
    )
    e2 = LearningEvent(learner_id=lid, type="quiz", text="answered", ts=t0 - timedelta(seconds=10))
    e3 = LearningEvent(learner_id=lid, type="note", text="latest", ts=t0)

    id1 = await storage.insert_event(e1)
    ids = await storage.insert_events([e3, e2])  # inserted out of ts order on purpose
    assert isinstance(id1, str) and all(isinstance(i, str) for i in ids)

    assert await storage.count_pending_events(lid) == 3
    pending = await storage.fetch_unconsolidated_events(lid)
    assert [p.text for p in pending] == ["what is a derivative?", "answered", "latest"]
    assert pending[0].id == id1
    assert pending[0].refs == {"session": "s1"}
    assert pending[0].signals == {"hesitation": 0.2}
    assert pending[0].ts == e1.ts
    assert pending[0].consolidated_at is None

    # limit applies after oldest-first ordering
    limited = await storage.fetch_unconsolidated_events(lid, limit=2)
    assert [p.text for p in limited] == ["what is a derivative?", "answered"]

    marked_at = _now()
    await storage.mark_events_consolidated([id1, ids[1]], ts=marked_at)
    assert await storage.count_pending_events(lid) == 1
    remaining = await storage.fetch_unconsolidated_events(lid)
    assert [p.text for p in remaining] == ["latest"]

    await storage.mark_events_consolidated([ids[0]])  # default ts = now
    assert await storage.count_pending_events(lid) == 0
    assert await storage.fetch_unconsolidated_events(lid) == []


async def test_learners_with_pending_events_quiet_filter(storage: PostgresStorage) -> None:
    quiet_lid = _learner()  # pending and quiet for 100s
    noisy_lid = _learner()  # pending but active just now
    done_lid = _learner()  # everything consolidated

    await storage.insert_event(
        LearningEvent(learner_id=quiet_lid, type="utterance", ts=_now() - timedelta(seconds=100))
    )
    await storage.insert_event(LearningEvent(learner_id=noisy_lid, type="utterance", ts=_now()))
    done_id = await storage.insert_event(
        LearningEvent(learner_id=done_lid, type="utterance", ts=_now() - timedelta(seconds=100))
    )
    await storage.mark_events_consolidated([done_id])

    everyone = await storage.learners_with_pending_events()
    assert quiet_lid in everyone
    assert noisy_lid in everyone
    assert done_lid not in everyone
    assert everyone == sorted(everyone)

    quiet_only = await storage.learners_with_pending_events(quiet_for_seconds=30)
    assert quiet_lid in quiet_only
    assert noisy_lid not in quiet_only
    assert done_lid not in quiet_only

    # A recent event (even consolidated) makes the learner "not quiet".
    recent_id = await storage.insert_event(
        LearningEvent(learner_id=quiet_lid, type="utterance", ts=_now())
    )
    await storage.mark_events_consolidated([recent_id])
    assert quiet_lid not in await storage.learners_with_pending_events(quiet_for_seconds=30)


# --- Nodes ---


async def test_node_upsert_get_and_filters(storage: PostgresStorage) -> None:
    lid = _learner()
    concept = Node(
        learner_id=lid,
        type=NodeType.CONCEPT,
        label="derivatives",
        summary="rate of change",
        mastery=0.4,
        confidence=0.7,
        salience=0.9,
        embedding=_embedding(0, 5),
        source_refs=[{"event": "e1"}],
    )
    pref = Node(learner_id=lid, type=NodeType.PREFERENCE, label="visual learner", salience=0.5)
    goal = Node(
        learner_id=lid,
        type=NodeType.GOAL,
        label="pass calc exam",
        salience=0.2,
        forgotten_at=_now(),
    )

    cid = await storage.upsert_node(concept)
    pid = await storage.upsert_node(pref)
    gid = await storage.upsert_node(goal)

    got = await storage.get_node(cid)
    assert got is not None
    assert got.id == cid
    assert got.type is NodeType.CONCEPT
    assert got.label == "derivatives"
    assert got.summary == "rate of change"
    assert got.mastery == pytest.approx(0.4)
    assert got.embedding is not None and len(got.embedding) == 1024
    assert got.embedding[5] == pytest.approx(1.0)
    assert got.source_refs == [{"event": "e1"}]
    assert got.created_at.tzinfo is not None

    # Upsert with existing id updates in place (no new row).
    got.label = "derivatives (updated)"
    got.salience = 0.95
    assert await storage.upsert_node(got) == cid
    refetched = await storage.get_node(cid)
    assert refetched is not None and refetched.label == "derivatives (updated)"

    # Ordering: salience DESC; forgotten excluded by default.
    nodes = await storage.get_nodes(lid)
    assert [n.id for n in nodes] == [cid, pid]
    with_forgotten = await storage.get_nodes(lid, include_forgotten=True)
    assert [n.id for n in with_forgotten] == [cid, pid, gid]
    prefs = await storage.get_nodes(lid, types=["preference"])
    assert [n.id for n in prefs] == [pid]

    assert await storage.get_node(str(uuid4())) is None


async def test_update_node_state_partial_and_noop(storage: PostgresStorage) -> None:
    lid = _learner()
    nid = await storage.upsert_node(
        Node(learner_id=lid, type=NodeType.CONCEPT, label="limits", mastery=0.1, salience=0.3)
    )

    await storage.update_node_state(nid)  # no kwargs: must be a no-op
    seen = _now()
    await storage.update_node_state(
        nid, mastery=0.8, summary="new summary", last_seen_at=seen, embedding=_embedding(7)
    )
    n = await storage.get_node(nid)
    assert n is not None
    assert n.mastery == pytest.approx(0.8)
    assert n.summary == "new summary"
    assert n.salience == pytest.approx(0.3)  # untouched
    assert n.last_seen_at == seen
    assert n.embedding is not None and n.embedding[7] == pytest.approx(1.0)
    assert n.forgotten_at is None

    gone = _now()
    await storage.update_node_state(nid, forgotten_at=gone, confidence=0.5)
    n = await storage.get_node(nid)
    assert n is not None and n.forgotten_at == gone and n.confidence == pytest.approx(0.5)


async def test_delete_node_cascades(storage: PostgresStorage) -> None:
    lid = _learner()
    a = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="a"))
    b = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="b"))
    await storage.upsert_edge(
        Edge(learner_id=lid, source_id=a, target_id=b, type=EdgeType.RELATES_TO)
    )
    await storage.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.NOTE, content="x"))
    await storage.insert_mastery_snapshot(a, 0.5, 0.5)

    await storage.delete_node(a)
    assert await storage.get_node(a) is None
    assert await storage.get_edges(lid) == []
    assert await storage.get_evidence(a) == []
    assert await storage.get_mastery_history(a) == []
    assert await storage.get_node(b) is not None


async def test_vector_search_orders_by_cosine_similarity(storage: PostgresStorage) -> None:
    lid = _learner()
    near = await storage.upsert_node(
        Node(learner_id=lid, type=NodeType.CONCEPT, label="near", embedding=_embedding(0))
    )
    mid_vec = _embedding(0)
    mid_vec[1] = 1.0  # 45 degrees from query
    mid = await storage.upsert_node(
        Node(learner_id=lid, type=NodeType.CONCEPT, label="mid", embedding=mid_vec)
    )
    far = await storage.upsert_node(
        Node(learner_id=lid, type=NodeType.GOAL, label="far", embedding=_embedding(2))
    )
    # Excluded: no embedding / forgotten.
    await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="no-vec"))
    await storage.upsert_node(
        Node(
            learner_id=lid,
            type=NodeType.CONCEPT,
            label="forgotten",
            embedding=_embedding(0),
            forgotten_at=_now(),
        )
    )

    query = _embedding(0)
    results = await storage.vector_search(lid, query, k=10)
    assert [n.id for n, _ in results] == [near, mid, far]
    sims = [s for _, s in results]
    assert sims[0] == pytest.approx(1.0, abs=1e-6)
    assert sims[1] == pytest.approx(0.7071, abs=1e-3)
    assert sims[2] == pytest.approx(0.0, abs=1e-6)
    assert sims == sorted(sims, reverse=True)

    assert [n.id for n, _ in await storage.vector_search(lid, query, k=2)] == [near, mid]
    only_goals = await storage.vector_search(lid, query, k=10, types=["goal"])
    assert [n.id for n, _ in only_goals] == [far]


# --- Edges ---


async def test_edge_dedupe_and_node_ids_filter(storage: PostgresStorage) -> None:
    lid = _learner()
    a = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="a"))
    b = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="b"))
    c = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="c"))

    e1 = await storage.upsert_edge(
        Edge(learner_id=lid, source_id=a, target_id=b, type=EdgeType.PREREQUISITE, weight=0.5)
    )
    # Same (learner, source, target, type) → same id, weight updated.
    e2 = await storage.upsert_edge(
        Edge(learner_id=lid, source_id=a, target_id=b, type=EdgeType.PREREQUISITE, weight=0.9)
    )
    assert e1 == e2
    # Different type → distinct edge.
    e3 = await storage.upsert_edge(
        Edge(learner_id=lid, source_id=a, target_id=b, type=EdgeType.RELATES_TO)
    )
    e4 = await storage.upsert_edge(
        Edge(learner_id=lid, source_id=b, target_id=c, type=EdgeType.PART_OF)
    )
    assert len({e1, e3, e4}) == 3

    edges = await storage.get_edges(lid)
    assert {e.id for e in edges} == {e1, e3, e4}
    deduped = next(e for e in edges if e.id == e1)
    assert deduped.weight == pytest.approx(0.9)
    assert deduped.type is EdgeType.PREREQUISITE
    assert deduped.source_id == a and deduped.target_id == b

    touching_c = await storage.get_edges(lid, node_ids=[c])
    assert {e.id for e in touching_c} == {e4}
    assert await storage.get_edges(lid, node_ids=[str(uuid4())]) == []


# --- Evidence ---


async def test_evidence_roundtrip_and_counts(storage: PostgresStorage) -> None:
    lid = _learner()
    nid = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="n"))
    bare = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="bare"))

    t0 = _now()
    old = Evidence(
        node_id=nid,
        kind=EvidenceKind.EXPLAINED,
        content="old",
        source_ref={"event": "e1"},
        importance=0.4,
        created_at=t0 - timedelta(seconds=20),
    )
    mid = Evidence(
        node_id=nid,
        kind=EvidenceKind.QUIZ_CORRECT,
        content="mid",
        created_at=t0 - timedelta(seconds=10),
    )
    new = Evidence(node_id=nid, kind=EvidenceKind.STRUGGLE, content="new", created_at=t0)
    for ev in (old, mid, new):
        assert isinstance(await storage.insert_evidence(ev), str)

    rows = await storage.get_evidence(nid)
    assert [r.content for r in rows] == ["new", "mid", "old"]  # newest first
    assert rows[2].kind is EvidenceKind.EXPLAINED
    assert rows[2].source_ref == {"event": "e1"}
    assert rows[2].importance == pytest.approx(0.4)
    assert rows[0].node_id == nid

    assert [r.content for r in await storage.get_evidence(nid, limit=2)] == ["new", "mid"]

    counts = await storage.evidence_counts([nid, bare])
    assert counts == {nid: 3, bare: 0}


# --- Audit + mastery history ---


async def test_audit_roundtrip_newest_first(storage: PostgresStorage) -> None:
    lid = _learner()
    t0 = _now()
    first = AuditEntry(
        learner_id=lid,
        op="extract",
        input_refs={"events": ["e1"]},
        output_refs={"nodes": ["n1"]},
        rationale="found a concept",
        model="extractor-1",
        tokens=123,
        cost=0.0042,
        ts=t0 - timedelta(seconds=5),
    )
    second = AuditEntry(learner_id=lid, op="recall", ts=t0)
    assert isinstance(await storage.insert_audit(first), str)
    assert isinstance(await storage.insert_audit(second), str)

    rows = await storage.get_audit(lid)
    assert [r.op for r in rows] == ["recall", "extract"]
    assert rows[1].input_refs == {"events": ["e1"]}
    assert rows[1].output_refs == {"nodes": ["n1"]}
    assert rows[1].tokens == 123
    assert rows[1].cost == pytest.approx(0.0042)
    assert rows[1].model == "extractor-1"
    assert [r.op for r in await storage.get_audit(lid, limit=1)] == ["recall"]


async def test_mastery_history_oldest_first(storage: PostgresStorage) -> None:
    lid = _learner()
    nid = await storage.upsert_node(Node(learner_id=lid, type=NodeType.CONCEPT, label="n"))
    t0 = _now()
    await storage.insert_mastery_snapshot(nid, 0.2, 0.5, ts=t0 - timedelta(seconds=10))
    await storage.insert_mastery_snapshot(nid, 0.6, None, ts=t0)
    await storage.insert_mastery_snapshot(nid, None, 0.9)  # default ts = now

    history = await storage.get_mastery_history(nid)
    assert len(history) == 3
    assert [ts for ts, _, _ in history] == sorted(ts for ts, _, _ in history)
    assert history[0][1] == pytest.approx(0.2)
    assert history[0][2] == pytest.approx(0.5)
    assert history[1] == (t0, pytest.approx(0.6), None)
    assert history[2][1] is None
    assert history[2][2] == pytest.approx(0.9)
