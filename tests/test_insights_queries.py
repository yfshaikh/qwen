from datetime import datetime, timedelta, timezone

from engram.core.engram import Engram
from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    LearningEvent,
    Node,
    NodeType,
)
from engram.insights import queries
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _eng(storage):
    return Engram(storage=storage, llm=FakeLLM(), embedder=FakeEmbedder())


def _node(store, nid, learner="L", **kw):
    store.nodes[nid] = Node(id=nid, learner_id=learner, type=NodeType.CONCEPT, label=nid, **kw)
    return store.nodes[nid]


async def test_mastery_history_scopes_to_learner_and_orders_by_ts():
    s = FakeStorage()
    _node(s, "a")
    _node(s, "b", learner="OTHER")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s._mastery = [
        {"node_id": "a", "mastery": 0.2, "confidence": 0.5, "ts": t0 + timedelta(days=1)},
        {"node_id": "a", "mastery": 0.1, "confidence": 0.4, "ts": t0},
        {"node_id": "b", "mastery": 0.9, "confidence": 0.9, "ts": t0},  # other learner
    ]
    rows = await s.mastery_history("L")
    assert [r["mastery"] for r in rows] == [0.1, 0.2]  # ordered, learner-scoped


async def test_evidence_counts_by_kind_per_node_scoped():
    s = FakeStorage()
    _node(s, "a")
    s.evidence = [
        Evidence(node_id="a", kind=EvidenceKind.QUIZ_WRONG),
        Evidence(node_id="a", kind=EvidenceKind.QUIZ_WRONG),
        Evidence(node_id="a", kind=EvidenceKind.STRUGGLE),
    ]
    rows = await s.evidence_counts_by_kind("L")
    got = {(r["node_id"], r["kind"]): r["count"] for r in rows}
    assert got[("a", "quiz_wrong")] == 2
    assert got[("a", "struggle")] == 1


async def test_event_counts_by_day_buckets():
    s = FakeStorage()
    # seed relative to now() so the `days` cutoff test never rots on the calendar.
    day = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0) \
        - timedelta(days=2)
    s.events = [
        LearningEvent(learner_id="L", type="utterance", text="x", ts=day),
        LearningEvent(learner_id="L", type="utterance", text="y", ts=day.replace(hour=18)),
        LearningEvent(learner_id="OTHER", type="utterance", text="z", ts=day),
    ]
    rows = await s.event_counts_by_day("L", days=365)
    assert rows == [{"day": day.date(), "count": 2}]


def test_summarize_empty_learner_returns_none_avgs():
    out = queries.summarize([], [], 0, [], sessions=0, last_active=None)
    assert out["concepts"] == 0 and out["avg_mastery"] is None and out["forgotten"] == 0


def test_summarize_counts_and_avgs():
    live = [Node(id="a", learner_id="L", type=NodeType.CONCEPT, label="a", mastery=0.4),
            Node(id="b", learner_id="L", type=NodeType.CONCEPT, label="b", mastery=0.6)]
    forgotten = Node(id="c", learner_id="L", type=NodeType.CONCEPT, label="c",
                     mastery=0.1, forgotten_at=datetime.now(timezone.utc))
    ev = [{"node_id": "a", "kind": "quiz_wrong", "count": 2}]
    out = queries.summarize(live, live + [forgotten], edge_count=1, evidence_rows=ev,
                            sessions=3, last_active=None)
    assert out["concepts"] == 2 and out["forgotten"] == 1
    assert out["avg_mastery"] == 0.5 and out["evidence"] == 2
    assert out["open_misconceptions"] == 1  # one node has quiz_wrong evidence


def test_trend_improving_vs_stuck():
    rows = [{"node_id": "a", "mastery": 0.2, "confidence": 0.5, "ts": datetime(2026,1,1,tzinfo=timezone.utc)},
            {"node_id": "a", "mastery": 0.7, "confidence": 0.9, "ts": datetime(2026,1,2,tzinfo=timezone.utc)},
            {"node_id": "b", "mastery": 0.3, "confidence": 0.5, "ts": datetime(2026,1,1,tzinfo=timezone.utc)}]
    assert queries.trend(rows) == {"a": "improving", "b": "stuck"}


async def test_insights_summary_end_to_end():
    s = FakeStorage()
    _node(s, "a", mastery=0.4, salience=0.5)
    out = await _eng(s).insights.summary("L")
    assert out["concepts"] == 1 and out["avg_mastery"] == 0.4


async def test_insights_review_queue_end_to_end():
    s = FakeStorage()
    _node(s, "limits", mastery=0.1)
    _node(s, "derivatives", mastery=0.2)
    s.edges = [Edge(learner_id="L", source_id="limits", target_id="derivatives",
                    type=EdgeType.PREREQUISITE)]
    q = await _eng(s).insights.review_queue("L", k=5)
    assert q[0]["node_id"] == "limits"


def test_summarize_none_salience_is_not_fading():
    # invariant #3 cold-start: a node with no salience yet must NOT count as
    # fading (agrees with review.py's None-handling).
    n = Node(id="a", learner_id="L", type=NodeType.CONCEPT, label="a",
             mastery=0.5, salience=None)
    assert queries.summarize([n], [n], 0, [], sessions=0, last_active=None)["fading"] == 0
