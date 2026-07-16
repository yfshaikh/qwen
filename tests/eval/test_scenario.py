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


def test_alias_forms_case_insensitive():
    from engram.eval.scenario import alias_forms
    aliases = {"Electromagnetic induction": ["EM induction", "induction"]}
    forms = alias_forms("electromagnetic INDUCTION", aliases)  # key match is ci
    assert "EM induction" in forms and "induction" in forms
    assert forms[0] == "electromagnetic INDUCTION"            # self always first
    assert alias_forms("Faraday's law", aliases) == ["Faraday's law"]  # no alias
    assert alias_forms("X", None) == ["X"]                    # None-safe


def test_load_scenario_reads_aliases(tmp_path):
    from engram.eval.scenario import load_scenario
    p = tmp_path / "s.yaml"
    p.write_text(
        "id: s\n"
        "probes:\n  - query: q\n    expect_nodes: [Foo]\n"
        "aliases:\n  Foo: [F, Foobar]\n")
    sc = load_scenario(str(p))
    assert sc.aliases == {"Foo": ["F", "Foobar"]}


# --- frozen transcripts -----------------------------------------------------
# A frozen session replays verbatim text instead of improvising from an intent,
# so the extractor is the only LLM that varies and a graph diff is attributable.

FROZEN = BASE + """
sessions:
  - transcript:
      - {role: user, content: "what is flux?"}
      - {role: assistant, content: "- Phi = B.A.cos(theta)"}
  - gap_days: 10
    transcript:
      - {role: user, content: "and Faraday's law?"}
      - {role: assistant, content: "- eps = -dPhi/dt"}
"""

def test_frozen_transcript_loads_and_derives_turns(tmp_path):
    sc = load_scenario(_write(tmp_path, FROZEN))
    assert sc.frozen is True
    assert [s.turns for s in sc.sessions] == [1, 1]        # turns derived from pairs
    assert sc.sessions[1].gap_days == 10.0
    assert sc.sessions[0].transcript[0]["content"] == "what is flux?"
    assert sc.sessions[0].frozen and not sc.sessions[0].intent

def test_generated_scenario_is_not_frozen(tmp_path):
    sc = load_scenario(_write(tmp_path, BASE + "sessions: [{intent: a}]\n"))
    assert sc.frozen is False and sc.sessions[0].frozen is False

def test_session_needs_exactly_one_of_intent_or_transcript(tmp_path):
    both = BASE + ("sessions:\n  - intent: a\n    transcript:\n"
                   "      - {role: user, content: hi}\n"
                   "      - {role: assistant, content: yo}\n")
    with pytest.raises(ValueError, match="exactly one of"):
        load_scenario(_write(tmp_path, both))
    with pytest.raises(ValueError, match="exactly one of"):
        load_scenario(_write(tmp_path, BASE + "sessions: [{turns: 2}]\n"))

def test_mixed_frozen_and_generated_rejected(tmp_path):
    """Half-replayed is neither reproducible nor realistic — refuse rather than
    produce a number nobody can interpret."""
    mixed = BASE + ("sessions:\n  - intent: a\n  - transcript:\n"
                    "      - {role: user, content: hi}\n"
                    "      - {role: assistant, content: yo}\n")
    with pytest.raises(ValueError, match="mixes frozen and generated"):
        load_scenario(_write(tmp_path, mixed))

@pytest.mark.parametrize("bad,match", [
    ("      - {role: user, content: hi}\n", "must be even"),
    ("      - {role: assistant, content: yo}\n      - {role: user, content: hi}\n",
     "must alternate"),
    ("      - {role: robot, content: hi}\n      - {role: assistant, content: yo}\n",
     "role must be one of"),
    ("      - {role: user, content: ''}\n      - {role: assistant, content: yo}\n",
     "empty content"),
])
def test_malformed_transcript_rejected(tmp_path, bad, match):
    """Strict on purpose: replay ingests each exchange as an (utterance,
    tutor_explanation) pair, so a dangling or misordered turn would silently drop
    events and quietly change what the run measures."""
    with pytest.raises(ValueError, match=match):
        load_scenario(_write(tmp_path, BASE + "sessions:\n  - transcript:\n" + bad))


# --- expect block + alias bridge --------------------------------------------

def test_expect_block_and_alias_bridge(tmp_path):
    """expect.concepts[].aliases is the single source of truth, but recall_probes
    and lifecycle read the flat scenario.aliases map. One edit site, both work."""
    p = _write(tmp_path, BASE + """
sessions: [{intent: a}]
aliases:
  Foo: [explicit-wins]
expect:
  concepts:
    - label: Foo
      aliases: [should-lose]
    - label: Bar
      aliases: [B, Barr]
  no_duplicates: true
  edges:
    required: [[Bar, Foo, prerequisite]]
""")
    sc = load_scenario(p)
    assert sc.expect["no_duplicates"] is True
    assert sc.expect["edges"]["required"] == [["Bar", "Foo", "prerequisite"]]
    assert sc.aliases["Bar"] == ["B", "Barr"]        # bridged from expect
    assert sc.aliases["Foo"] == ["explicit-wins"]    # top-level overrides

def test_expect_defaults_to_empty(tmp_path):
    sc = load_scenario(_write(tmp_path, BASE + "sessions: [{intent: a}]\n"))
    assert sc.expect == {}


@pytest.fixture
def _registered():
    """Re-register the checks. Mirrors test_checks_graph.py / test_runner.py:
    test_registry's autouse clear_registry() can empty the registry first, and
    import caching means @check won't re-fire on a plain import."""
    import importlib

    from engram.eval.registry import clear_registry
    clear_registry()
    for name in ("recall_probes", "integrity", "edges", "abstention",
                 "knowledge_update", "concepts", "preferences", "dedup",
                 "importance", "lifecycle", "behavior"):
        importlib.reload(importlib.import_module(f"engram.eval.checks.{name}"))


@pytest.mark.parametrize("name", ["em-frozen-v1", "sat-linear-holdout-v1"])
def test_shipped_frozen_fixture_stays_loadable(_registered, name):
    """The committed benchmarks are the gates an agent iterates against. If one
    stops loading, or names a check nobody registered, every downstream run is
    meaningless — and it would surface as a run `error`, which is easy to skim
    past. Fail here instead, in the fast suite.
    """
    import pathlib

    from engram.eval.registry import get_check

    root = pathlib.Path(__file__).resolve().parents[2]
    sc = load_scenario(root / "eval" / "scenarios" / f"{name}.yaml")
    assert sc.frozen, f"{name} must be fully frozen or it isn't a gate"
    for c in sc.checks:
        get_check(c.name)  # raises KeyError if unregistered
    # Ground truth the checks read; an empty block means they'd vacuously pass —
    # a gate that cannot fail is worse than no gate, because it reads as verified.
    assert sc.expect["concepts"] and sc.expect["edges"]["required"]
    assert sc.expect["edges"]["forbidden"] and sc.expect["abstention"]
    assert sc.expect["mastery"]


@pytest.mark.parametrize("name", ["em-frozen-v1", "sat-linear-holdout-v1"])
def test_abstention_targets_never_appear_in_transcript(_registered, name):
    """`abstention` asserts the extractor invented a topic from its own weights. If
    the topic is sitting in the transcript, the check scores recall instead — it
    goes red on a CORRECT extraction and the fixture silently tests the opposite of
    what it claims. Cheap to get wrong while editing a transcript; invisible until
    you are debugging a fix that was never broken.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    sc = load_scenario(root / "eval" / "scenarios" / f"{name}.yaml")
    text = " ".join(t["content"] for s in sc.sessions for t in s.transcript).lower()
    leaked = [t for t in sc.expect.get("abstention", []) if str(t).lower() in text]
    assert not leaked, f"{name}: abstention targets appear in the transcript: {leaked}"
