import uuid

from engram.adapters.storage.postgres import PostgresStorage
from engram.core.consolidation import ConsolidationPlan
from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)


def _vec(*lead):
    v = [0.0] * 1024
    for i, x in enumerate(lead):
        v[i] = float(x)
    return v


async def test_get_pending_events_and_live_nodes(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        await s.insert_events([LearningEvent(learner_id=learner, type="note", text="n")])
        pending = await s.get_pending_events(learner)
        assert len(pending) == 1 and pending[0].id is not None
        await s.insert_node(Node(learner_id=learner, type=NodeType.CONCEPT, label="A",
                                 embedding=_vec(1, 0)))
        live = await s.get_live_nodes(learner)
        assert [n.label for n in live] == ["A"]
    finally:
        await s.close()


async def test_consolidation_lock_blocks_second(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        async with s.consolidation_lock(learner) as first:
            assert first is True
            async with s.consolidation_lock(learner) as second:
                assert second is False
        async with s.consolidation_lock(learner) as again:
            assert again is True
    finally:
        await s.close()


async def test_apply_consolidation_atomic_and_remaps(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        ids = await s.insert_events([LearningEvent(learner_id=learner, type="note", text="n")])
        plan = ConsolidationPlan(
            learner_id=learner,
            new_nodes=[Node(id="tmp-0", learner_id=learner, type=NodeType.CONCEPT,
                            label="X", salience=1.0, embedding=_vec(1, 0))],
            new_evidence=[Evidence(node_id="tmp-0", kind=EvidenceKind.NOTE, content="c")],
            processed_event_ids=ids,
        )
        await s.apply_consolidation(plan)

        live = await s.get_live_nodes(learner)
        assert [n.label for n in live] == ["X"]
        real_id = live[0].id
        ev = await s.top_evidence([real_id], per_node=2)
        assert ev[real_id][0].content == "c"
        assert (await s.get_pending_events(learner)) == []  # watermarked
    finally:
        await s.close()


async def test_apply_consolidation_rolls_back_on_error(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        bad_edge = Edge(learner_id=learner, source_id="tmp-0",
                        target_id=str(uuid.uuid4()),  # nonexistent real id -> FK violation
                        type=EdgeType.PREREQUISITE)
        plan = ConsolidationPlan(
            learner_id=learner,
            new_nodes=[Node(id="tmp-0", learner_id=learner, type=NodeType.CONCEPT,
                            label="ShouldNotPersist", salience=1.0, embedding=_vec(1, 0))],
            new_edges=[bad_edge],
        )
        try:
            await s.apply_consolidation(plan)
        except Exception:
            pass
        live = await s.get_live_nodes(learner)
        assert live == []  # the new node rolled back with the failed edge
    finally:
        await s.close()
