from engram.core.models import Edge, EdgeType, Node, NodeType
from engram.insights import review


def _n(nid, mastery, salience=0.5, importance=0.5):
    return Node(id=nid, learner_id="L", type=NodeType.CONCEPT, label=nid,
                mastery=mastery, salience=salience, importance=importance)


def _pre(src, tgt):  # src is a prerequisite of tgt
    return Edge(learner_id="L", source_id=src, target_id=tgt, type=EdgeType.PREREQUISITE)


def test_due_score_weak_and_unlocking_ranks_first():
    weak_unlocker = _n("limits", 0.1)
    strong = _n("trivia", 0.9)
    q = review.review_queue([weak_unlocker, strong],
                            [_pre("limits", "derivatives")], struggle_by_node={}, k=5)
    assert q[0]["node_id"] == "limits"
    assert "weak" in q[0]["reason"]


def test_review_queue_reason_mentions_prereq_count():
    q = review.review_queue(
        [_n("limits", 0.2), _n("derivatives", 0.3), _n("integrals", 0.3)],
        [_pre("limits", "derivatives"), _pre("limits", "integrals")],
        struggle_by_node={}, k=5)
    top = next(i for i in q if i["node_id"] == "limits")
    assert "prerequisite of 2" in top["reason"]


def test_blockers_walks_prereq_ancestors_of_target():
    # goal depends on derivatives depends on limits; limits is the weak ancestor.
    nodes = [_n("limits", 0.1), _n("derivatives", 0.7), _n("goal", 0.8, importance=0.95)]
    edges = [_pre("limits", "derivatives"), _pre("derivatives", "goal")]
    out = review.blockers(nodes, edges, target_ids=["goal"])
    ids = {b["node_id"] for b in out}
    assert "limits" in ids
    assert out[0]["path"][0] == "goal"  # path starts at the target it blocks


def test_empty_inputs_return_empty():
    assert review.review_queue([], [], {}, 5) == []
    assert review.blockers([], [], None) == []


def test_reason_reports_fading_at_zero_salience_but_not_when_none():
    # invariant #3: salience 0.0 IS fading (must not be swallowed by `or 1.0`);
    # salience None is "no decay signal" == NOT fading. Reason text must agree
    # with due_score / queries.summarize at both boundaries.
    faded = review.review_queue([_n("x", 0.9, salience=0.0)], [], {}, 5)
    assert "fading" in faded[0]["reason"]
    unknown = review.review_queue([_n("y", 0.9, salience=None)], [], {}, 5)
    assert "fading" not in unknown[0]["reason"]
