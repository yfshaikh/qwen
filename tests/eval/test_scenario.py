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
