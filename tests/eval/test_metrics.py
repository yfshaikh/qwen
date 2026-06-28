from engram.eval.arms import ProbeScore, TurnRecord
from engram.eval.metrics import aggregate_behavior, aggregate_recall, judge_turn
from tests.fakes import FakeLLM


def test_aggregate_recall():
    scores = [
        ProbeScore("q1", hit=["A", "B"], missing=[], ranks={"A": 1, "B": 2}, leaked=False),
        ProbeScore("q2", hit=["A"], missing=["B"], ranks={"A": 1, "B": 3}, leaked=True),
    ]
    agg = aggregate_recall(scores)
    assert agg["node_hit_rate"] == 0.75   # 3 hits of 4 expected
    assert agg["full_hit_rate"] == 0.5    # 1 of 2 probes fully hit
    assert agg["mean_rank"] == (1 + 2 + 1 + 3) / 4
    assert agg["mastered_leak_rate"] == 0.5


def test_aggregate_behavior():
    j = [
        {"re_explained": True, "preference_honored": True, "adapt_score": 4},
        {"re_explained": False, "preference_honored": True, "adapt_score": 2},
    ]
    agg = aggregate_behavior(j)
    assert agg["re_explanation_rate"] == 0.5
    assert agg["preference_honored_rate"] == 1.0
    assert agg["mean_adapt_score"] == 3.0


async def test_judge_turn_parses_text_json():
    llm = FakeLLM(canned_text='{"re_explained": false, "preference_honored": true, "adapt_score": 5}')
    out = await judge_turn(llm, TurnRecord("q", "reply", "ctx"), {"mastered": ["Limit"]})
    assert out == {"re_explained": False, "preference_honored": True, "adapt_score": 5}
