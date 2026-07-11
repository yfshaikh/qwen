import pytest
from engram.eval.scenario import load_scenario

YAML = """
id: tiny
persona: a student
hidden_state:
  mastered: [Continuity]
  preference: concrete examples
sessions:
  - intent: ask about limits
    turns: 2
probes:
  - query: what next?
    expect_nodes: [Limit]
    mastered_not_expected: [Continuity]
"""

def test_load_scenario_parses(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(YAML)
    sc = load_scenario(p)
    assert sc.id == "tiny"
    assert sc.sessions[0].turns == 2
    assert sc.probes[0].expect_nodes == ["Limit"]
    assert sc.probes[0].mastered_not_expected == ["Continuity"]
    assert sc.hidden_state["preference"] == "concrete examples"

def test_session_turns_defaults_to_3(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(YAML.replace("    turns: 2\n", ""))
    assert load_scenario(p).sessions[0].turns == 3

def test_missing_probes_raises(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("id: x\npersona: y\nsessions: []\n")
    with pytest.raises(ValueError, match="probes"):
        load_scenario(p)


def _write(tmp_path, text):
    p = tmp_path / "s.yaml"
    p.write_text(text)
    return p

BASE = """
id: t
probes: [{query: q, expect_nodes: [X]}]
"""

def test_scenario_v2_gap_days_and_checks(tmp_path):
    p = _write(tmp_path, BASE + """
sessions:
  - intent: first
    turns: 1
  - intent: later
    gap_days: 30
checks:
  - dedup
  - name: lifecycle
    expect: {forgotten: [Old], kept: [Fresh]}
    threshold: 0.1
""")
    sc = load_scenario(p)
    assert sc.sessions[0].gap_days == 0.0
    assert sc.sessions[1].gap_days == 30.0
    assert [c.name for c in sc.checks] == ["dedup", "lifecycle"]
    assert sc.checks[0].params == {}
    assert sc.checks[1].params == {"expect": {"forgotten": ["Old"], "kept": ["Fresh"]},
                                   "threshold": 0.1}

def test_scenario_v2_defaults_backcompat(tmp_path):
    sc = load_scenario(_write(tmp_path, BASE + "sessions: [{intent: a}]\n"))
    assert sc.checks == [] and sc.sessions[0].gap_days == 0.0

def test_scenario_v2_negative_gap_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_scenario(_write(tmp_path, BASE + "sessions: [{intent: a, gap_days: -1}]\n"))
