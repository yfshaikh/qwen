"""Live round-trip tests for `PostgresStorage` against Postgres 16 + pgvector.

Bring the database up first (e.g. `docker compose up -d db`) and point
`DATABASE_URL` at it. The whole module SKIPS gracefully when the DB is
unreachable, so the suite stays green in environments without one.

Every test uses a unique `learner_id` (``test-<uuid4>``) so concurrent runs and
repeated runs never interfere — no global cleanup required.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from engram.adapters.llm.embeddings import HashingEmbedder
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
from engram.core.models import _now

_EMBEDDER = HashingEmbedder(dim=1024)


def _vec(*indices_and_values: tuple[int, float]) -> list[float]:
    """A length-1024 embedding with a few non-zero slots set."""
    v = [0.0] * 1024
    for idx, val in indices_and_values:
        v[idx] = val
    return v


async def _embed(text: str) -> list[float]:
    return (await _EMBEDDER.embed([text]))[0]


@pytest.fixture
async def storage(database_url: str) -> PostgresStorage:
    """A connected `PostgresStorage`, or skip the whole module if no DB."""
    store = PostgresStorage(database_url)
    try:
        await store.connect()
        if not await store.health():
            raise RuntimeError("health() returned False")
    except Exception as exc:  # noqa: BLE001 — any failure means "no usable DB"
        await store.close()
        pytest.skip(f"Postgres not available for live tests: {exc}")
    try:
        yield store
    finally:
        await store.close()


# --- health (kept from the original suite) ---------------------------------


async def test_health_true_against_live_db(database_url: str) -> None:
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        assert await storage.health() is True
    finally:
        await storage.close()


async def test_health_false_when_db_unreachable() -> None:
    # Unused port; connection must fail fast and health() must return False.
    storage = PostgresStorage("postgresql://engram:engram@127.0.0.1:1/engram")
    # connect() may itself raise — that's fine; health() is the contract.
    try:
        await storage.connect()
    except Exception:
        pass
    assert await storage.health() is False


# --- events ----------------------------------------------------------------


async def test_event_lifecycle(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    now = _now()
    e1 = LearningEvent(
        learner_id=learner,
        type="utterance",
        text="older",
        refs={"k": "v"},
        signals={"s": 1},
        ts=now - timedelta(minutes=5),
    )
    e2 = LearningEvent(
        learner_id=learner,
        type="utterance",
        text="newer",
        ts=now - timedelta(minutes=1),
    )

    ids = await storage.insert_events([e1, e2])
    assert len(ids) == 2
    assert all(isinstance(i, str) for i in ids)

    assert await storage.count_pending_events(learner) == 2

    pending = await storage.fetch_unconsolidated_events(learner)
    assert [p.text for p in pending] == ["older", "newer"]  # oldest-first
    first = pending[0]
    assert first.refs == {"k": "v"}
    assert first.signals == {"s": 1}
    assert first.id == ids[0]
    assert first.ts.tzinfo is not None
    assert first.consolidated_at is None

    # Consolidate the older one; it leaves the pending queue.
    await storage.mark_events_consolidated([ids[0]])
    assert await storage.count_pending_events(learner) == 1
    still_pending = await storage.fetch_unconsolidated_events(learner)
    assert [p.text for p in still_pending] == ["newer"]


async def test_insert_event_preserves_supplied_id(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    supplied = str(uuid4())
    eid = await storage.insert_event(
        LearningEvent(learner_id=learner, type="note", text="hi", id=supplied)
    )
    assert eid == supplied
    rows = await storage.fetch_unconsolidated_events(learner)
    assert rows[0].id == supplied


async def test_fetch_unconsolidated_respects_limit(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    now = _now()
    await storage.insert_events(
        [
            LearningEvent(
                learner_id=learner,
                type="note",
                text=str(i),
                ts=now - timedelta(minutes=10 - i),
            )
            for i in range(5)
        ]
    )
    limited = await storage.fetch_unconsolidated_events(learner, limit=2)
    assert [e.text for e in limited] == ["0", "1"]


async def test_learners_with_pending_events_quiet_filter(storage: PostgresStorage) -> None:
    quiet = f"test-{uuid4()}"
    noisy = f"test-{uuid4()}"
    now = _now()
    # `quiet` last spoke 1h ago; `noisy` just now.
    await storage.insert_event(
        LearningEvent(learner_id=quiet, type="note", ts=now - timedelta(hours=1))
    )
    await storage.insert_event(LearningEvent(learner_id=noisy, type="note", ts=now))

    all_pending = await storage.learners_with_pending_events(quiet_for_seconds=0)
    assert quiet in all_pending and noisy in all_pending
    assert all_pending == sorted(all_pending)

    # With a 60s quiet window, only the long-quiet learner qualifies.
    quiet_only = await storage.learners_with_pending_events(quiet_for_seconds=60)
    assert quiet in quiet_only
    assert noisy not in quiet_only


async def test_consolidated_events_excluded_from_pending(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    eid = await storage.insert_event(LearningEvent(learner_id=learner, type="note"))
    await storage.mark_events_consolidated([eid])
    assert await storage.count_pending_events(learner) == 0
    assert learner not in await storage.learners_with_pending_events()


# --- nodes -----------------------------------------------------------------


async def test_node_upsert_insert_and_get(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    node = Node(
        learner_id=learner,
        type=NodeType.CONCEPT,
        label="Photosynthesis",
        summary="plants make food",
        mastery=0.4,
        confidence=0.5,
        salience=0.9,
        embedding=_vec((0, 1.0)),
        source_refs=[{"event": "e1"}, "raw"],
    )
    nid = await storage.upsert_node(node)
    assert isinstance(nid, str)

    got = await storage.get_node(nid)
    assert got is not None
    assert got.id == nid
    assert got.learner_id == learner
    assert got.type is NodeType.CONCEPT
    assert got.label == "Photosynthesis"
    assert got.summary == "plants make food"
    assert got.mastery == pytest.approx(0.4)
    assert got.confidence == pytest.approx(0.5)
    assert got.salience == pytest.approx(0.9)
    assert got.embedding is not None and len(got.embedding) == 1024
    assert got.embedding[0] == pytest.approx(1.0)
    assert got.source_refs == [{"event": "e1"}, "raw"]
    assert got.forgotten_at is None
    assert got.created_at.tzinfo is not None


async def test_node_upsert_updates_existing(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    nid = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.GOAL, label="Run a 5k", mastery=0.1)
    )
    # Re-upsert with the same id and changed fields.
    same = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.GOAL,
            label="Run a 10k",
            mastery=0.8,
            id=nid,
        )
    )
    assert same == nid
    got = await storage.get_node(nid)
    assert got is not None
    assert got.label == "Run a 10k"
    assert got.mastery == pytest.approx(0.8)
    # Still exactly one node for this learner.
    assert len(await storage.get_nodes(learner)) == 1


async def test_get_node_missing_returns_none(storage: PostgresStorage) -> None:
    assert await storage.get_node(str(uuid4())) is None


async def test_get_nodes_filters_and_ordering(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="low", salience=0.1)
    )
    await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="high", salience=0.9)
    )
    await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.PREFERENCE, label="pref", salience=0.5)
    )
    forgotten = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="gone", salience=0.99)
    )
    await storage.update_node_state(forgotten, forgotten_at=_now())

    # Default: non-forgotten, salience desc.
    default = await storage.get_nodes(learner)
    labels = [n.label for n in default]
    assert "gone" not in labels
    assert labels == ["high", "pref", "low"]  # salience desc

    # Type filter (string values, matching the Protocol).
    concepts = await storage.get_nodes(learner, types=["concept"])
    assert {n.label for n in concepts} == {"high", "low"}

    # include_forgotten surfaces the forgotten node.
    with_forgotten = await storage.get_nodes(learner, include_forgotten=True)
    assert "gone" in {n.label for n in with_forgotten}


async def test_update_node_state_partial(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    nid = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="x",
            mastery=0.2,
            confidence=0.3,
            summary="orig",
            embedding=_vec((5, 1.0)),
        )
    )
    seen = _now()
    await storage.update_node_state(
        nid,
        mastery=0.95,
        salience=0.7,
        last_seen_at=seen,
        summary="updated",
        embedding=_vec((6, 1.0)),
    )
    got = await storage.get_node(nid)
    assert got is not None
    assert got.mastery == pytest.approx(0.95)
    assert got.salience == pytest.approx(0.7)
    assert got.summary == "updated"
    assert got.embedding is not None and got.embedding[6] == pytest.approx(1.0)
    # Untouched field keeps its original value.
    assert got.confidence == pytest.approx(0.3)


async def test_update_node_state_noop_when_all_none(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    nid = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="x", mastery=0.5)
    )
    await storage.update_node_state(nid)  # no kwargs -> no-op
    got = await storage.get_node(nid)
    assert got is not None and got.mastery == pytest.approx(0.5)


async def test_delete_node_cascades(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    a = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="a")
    )
    b = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="b")
    )
    await storage.upsert_edge(
        Edge(learner_id=learner, source_id=a, target_id=b, type=EdgeType.RELATES_TO)
    )
    await storage.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.NOTE, content="n"))

    await storage.delete_node(a)
    assert await storage.get_node(a) is None
    # FK ON DELETE CASCADE removed the edge and evidence too.
    assert await storage.get_edges(learner) == []
    assert await storage.get_evidence(a) == []


# --- vector search ---------------------------------------------------------


async def test_vector_search_orders_by_similarity(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    near = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="near",
            embedding=_vec((0, 1.0)),
        )
    )
    mid = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="mid",
            embedding=_vec((0, 1.0), (1, 1.0)),
        )
    )
    far = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="far",
            embedding=_vec((1, 1.0)),
        )
    )

    results = await storage.vector_search(learner, _vec((0, 1.0)), k=3)
    assert [n.id for n, _ in results] == [near, mid, far]  # most similar first

    sims = [s for _, s in results]
    assert sims[0] == pytest.approx(1.0, abs=1e-6)  # identical vector
    assert sims[1] > sims[2]
    assert sims == sorted(sims, reverse=True)


async def test_vector_search_respects_k_filters_and_forgotten(
    storage: PostgresStorage,
) -> None:
    learner = f"test-{uuid4()}"
    await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="c",
            embedding=_vec((0, 1.0)),
        )
    )
    await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.PREFERENCE,
            label="p",
            embedding=_vec((0, 1.0)),
        )
    )
    forgotten = await storage.upsert_node(
        Node(
            learner_id=learner,
            type=NodeType.CONCEPT,
            label="gone",
            embedding=_vec((0, 1.0)),
        )
    )
    await storage.update_node_state(forgotten, forgotten_at=_now())
    # A node with no embedding must never appear.
    await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="noemb")
    )

    # k caps the result count.
    assert len(await storage.vector_search(learner, _vec((0, 1.0)), k=1)) == 1

    # Type filter + forgotten exclusion: only the live concept "c".
    typed = await storage.vector_search(learner, _vec((0, 1.0)), k=10, types=["concept"])
    assert [n.label for n, _ in typed] == ["c"]

    # Without a type filter, the forgotten + embedding-less nodes still excluded.
    untyped = await storage.vector_search(learner, _vec((0, 1.0)), k=10)
    assert {n.label for n, _ in untyped} == {"c", "p"}


async def test_vector_search_scoped_to_learner(storage: PostgresStorage) -> None:
    mine = f"test-{uuid4()}"
    theirs = f"test-{uuid4()}"
    await storage.upsert_node(
        Node(learner_id=mine, type=NodeType.CONCEPT, label="m", embedding=_vec((0, 1.0)))
    )
    await storage.upsert_node(
        Node(learner_id=theirs, type=NodeType.CONCEPT, label="t", embedding=_vec((0, 1.0)))
    )
    results = await storage.vector_search(mine, _vec((0, 1.0)), k=10)
    assert {n.learner_id for n, _ in results} == {mine}


# --- edges -----------------------------------------------------------------


async def test_edge_dedupe_and_get(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    a = await storage.upsert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="a"))
    b = await storage.upsert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="b"))
    c = await storage.upsert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="c"))

    first = await storage.upsert_edge(
        Edge(learner_id=learner, source_id=a, target_id=b, type=EdgeType.RELATES_TO, weight=1.0)
    )
    # Same (learner, source, target, type) -> dedupe, return same id, update weight.
    dup = await storage.upsert_edge(
        Edge(learner_id=learner, source_id=a, target_id=b, type=EdgeType.RELATES_TO, weight=2.5)
    )
    assert dup == first

    # Different type is a distinct edge.
    other = await storage.upsert_edge(
        Edge(learner_id=learner, source_id=a, target_id=c, type=EdgeType.PREREQUISITE)
    )
    assert other != first

    edges = await storage.get_edges(learner)
    assert len(edges) == 2
    by_id = {e.id: e for e in edges}
    assert by_id[first].weight == pytest.approx(2.5)  # weight updated by dedupe
    assert by_id[first].type is EdgeType.RELATES_TO
    assert by_id[first].source_id == a and by_id[first].target_id == b

    # node_ids filter: edges touching `c` only.
    touching_c = await storage.get_edges(learner, node_ids=[c])
    assert {e.id for e in touching_c} == {other}


async def test_get_edges_scoped_to_learner(storage: PostgresStorage) -> None:
    mine = f"test-{uuid4()}"
    theirs = f"test-{uuid4()}"
    a = await storage.upsert_node(Node(learner_id=mine, type=NodeType.CONCEPT, label="a"))
    b = await storage.upsert_node(Node(learner_id=mine, type=NodeType.CONCEPT, label="b"))
    x = await storage.upsert_node(Node(learner_id=theirs, type=NodeType.CONCEPT, label="x"))
    y = await storage.upsert_node(Node(learner_id=theirs, type=NodeType.CONCEPT, label="y"))
    await storage.upsert_edge(
        Edge(learner_id=mine, source_id=a, target_id=b, type=EdgeType.PART_OF)
    )
    await storage.upsert_edge(
        Edge(learner_id=theirs, source_id=x, target_id=y, type=EdgeType.PART_OF)
    )
    assert all(e.learner_id == mine for e in await storage.get_edges(mine))


# --- evidence --------------------------------------------------------------


async def test_evidence_insert_get_and_counts(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    node = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="n")
    )
    other = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="m")
    )

    now = _now()
    ev_old = await storage.insert_evidence(
        Evidence(
            node_id=node,
            kind=EvidenceKind.EXPLAINED,
            content="old",
            source_ref={"event": "e1"},
            embedding=_vec((3, 1.0)),
            importance=0.2,
            created_at=now - timedelta(minutes=5),
        )
    )
    await storage.insert_evidence(
        Evidence(
            node_id=node,
            kind=EvidenceKind.QUIZ_CORRECT,
            content="new",
            created_at=now,
        )
    )

    rows = await storage.get_evidence(node)
    assert [e.content for e in rows] == ["new", "old"]  # newest-first
    oldest = rows[-1]
    assert oldest.id == ev_old
    assert oldest.node_id == node
    assert oldest.kind is EvidenceKind.EXPLAINED
    assert oldest.source_ref == {"event": "e1"}
    assert oldest.embedding is not None and oldest.embedding[3] == pytest.approx(1.0)
    assert oldest.importance == pytest.approx(0.2)

    # limit caps results (still newest-first).
    assert [e.content for e in await storage.get_evidence(node, limit=1)] == ["new"]

    counts = await storage.evidence_counts([node, other, str(uuid4())])
    assert counts[node] == 2
    assert counts[other] == 0  # no evidence -> 0, not missing
    assert all(v == 0 for k, v in counts.items() if k != node)


async def test_evidence_counts_empty_input(storage: PostgresStorage) -> None:
    assert await storage.evidence_counts([]) == {}


# --- audit -----------------------------------------------------------------


async def test_audit_insert_and_get(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    now = _now()
    await storage.insert_audit(
        AuditEntry(
            learner_id=learner,
            op="extract",
            input_refs={"events": ["e1"]},
            output_refs={"nodes": ["n1"]},
            rationale="because",
            model="test-model",
            tokens=123,
            cost=0.0042,
            ts=now - timedelta(minutes=1),
        )
    )
    await storage.insert_audit(
        AuditEntry(learner_id=learner, op="recall", ts=now)
    )

    rows = await storage.get_audit(learner)
    assert [a.op for a in rows] == ["recall", "extract"]  # newest-first
    extract = rows[-1]
    assert extract.input_refs == {"events": ["e1"]}
    assert extract.output_refs == {"nodes": ["n1"]}
    assert extract.rationale == "because"
    assert extract.model == "test-model"
    assert extract.tokens == 123
    assert extract.cost == pytest.approx(0.0042)
    assert extract.ts.tzinfo is not None

    assert [a.op for a in await storage.get_audit(learner, limit=1)] == ["recall"]


async def test_audit_scoped_to_learner(storage: PostgresStorage) -> None:
    mine = f"test-{uuid4()}"
    theirs = f"test-{uuid4()}"
    await storage.insert_audit(AuditEntry(learner_id=mine, op="recall"))
    await storage.insert_audit(AuditEntry(learner_id=theirs, op="recall"))
    rows = await storage.get_audit(mine)
    assert len(rows) == 1 and rows[0].learner_id == mine


# --- mastery history -------------------------------------------------------


async def test_mastery_snapshot_and_history(storage: PostgresStorage) -> None:
    learner = f"test-{uuid4()}"
    node = await storage.upsert_node(
        Node(learner_id=learner, type=NodeType.CONCEPT, label="n")
    )
    now = _now()
    await storage.insert_mastery_snapshot(node, 0.3, 0.4, ts=now - timedelta(minutes=2))
    await storage.insert_mastery_snapshot(node, 0.6, None, ts=now - timedelta(minutes=1))
    await storage.insert_mastery_snapshot(node, 0.9, 0.8, ts=now)

    history = await storage.get_mastery_history(node)
    assert [m for _, m, _ in history] == pytest.approx([0.3, 0.6, 0.9])  # oldest-first
    ts_values = [ts for ts, _, _ in history]
    assert ts_values == sorted(ts_values)
    assert all(ts.tzinfo is not None for ts in ts_values)
    # Nullable confidence round-trips as None.
    assert history[1][2] is None


async def test_mastery_history_empty(storage: PostgresStorage) -> None:
    assert await storage.get_mastery_history(str(uuid4())) == []
