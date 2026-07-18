from engram.eval.arms import ProbeScore, score_probe
from engram.eval.scenario import Probe


def test_score_probe_hit_and_rank():
    probe = Probe(query="q", expect_nodes=["Limit", "Goal"], mastered_not_expected=["Continuity"])
    score: ProbeScore = score_probe(["Goal", "Limit", "Calculus"], probe)
    assert score.hit == ["Limit", "Goal"]
    assert score.missing == []
    assert score.ranks == {"Limit": 2, "Goal": 1}
    assert score.leaked is False


def test_score_probe_missing_and_leak():
    probe = Probe(query="q", expect_nodes=["Limit"], mastered_not_expected=["Continuity"])
    score: ProbeScore = score_probe(["Continuity", "Calculus"], probe)
    assert score.missing == ["Limit"]
    assert score.ranks["Limit"] == 3  # len(ordered)+1 penalty
    assert score.leaked is True  # mastered concept is the top result


def test_score_probe_substring_match():
    probe = Probe(query="q", expect_nodes=["Pass calculus final"], mastered_not_expected=[])
    score: ProbeScore = score_probe(["Pass calculus final next month"], probe)
    assert score.hit == ["Pass calculus final"]
