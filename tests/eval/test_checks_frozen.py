"""Mutation tests for the frozen-benchmark checks.

EVERY test here is a pair: a GREEN graph the check passes, and a MUTATED graph
carrying one specific bug that the check must go RED on. A check that only ever
passes is decoration, not a gate — and these four exist precisely because an agent
will iterate against them and needs to be told when it is wrong.

The bugs mutated in are the real ones from docs/superpowers/roadmap.md §3.1:
duplicate concepts, missing/reversed prerequisite edges (direction churn from
keeper.py:191), hallucinated curriculum (from run edb608f6), and a misconception
correction that never reaches the graph.
"""
import importlib

import pytest

import engram.eval.checks  # noqa: F401  (registration)
from engram.eval.checks import abstention, concepts, edges, knowledge_update, preferences
from engram.eval.registry import EvalContext, clear_registry, get_check, run_check
from engram.eval.scenario import Scenario


@pytest.fixture(autouse=True)
def _register_checks():
    # Mirrors test_checks_graph.py: test_registry's autouse clear_registry() can
    # empty the registry first, and import caching won't re-fire @check.
    clear_registry()
    for mod in (concepts, edges, abstention, knowledge_update, preferences):
        importlib.reload(mod)


def _node(nid, label, *, ntype="concept", mastery=None, forgotten=None):
    return {"id": nid, "label": label, "type": ntype, "mastery": mastery,
            "embedding": None, "forgotten_at": forgotten}


def _snap(nodes, graph_edges=None, session=0):
    return {"session": session, "sim_ts": "t", "report": {},
            "graph": {"nodes": nodes, "edges": graph_edges or [], "evidence": {}}}


def _scenario(expect, aliases=None):
    return Scenario(id="t", persona="", hidden_state={}, sessions=[], probes=[],
                    aliases=aliases or {}, expect=expect)


def _ctx(snaps, scenario):
    return EvalContext(eng=None, scenario=scenario, learner_id="x",
                       snapshots=snaps, transcript=[], clock=None, params={})


# --- the "correct" graph the mutations depart from -------------------------

FLUX = _node("1", "Magnetic flux")
FARADAY = _node("2", "Faraday's law")
TRANSFORMER = _node("3", "Transformer")
GOOD_NODES = [FLUX, FARADAY, TRANSFORMER]
GOOD_EDGES = [
    {"source": "1", "target": "2", "type": "prerequisite", "weight": 1.0},
    {"source": "2", "target": "3", "type": "prerequisite", "weight": 1.0},
]
CONCEPT_EXPECT = {"concepts": [{"label": "Magnetic flux"}, {"label": "Faraday's law"},
                               {"label": "Transformer"}],
                  "no_duplicates": True}
EDGE_EXPECT = {"edges": {
    "required": [["Magnetic flux", "Faraday's law", "prerequisite"],
                 ["Faraday's law", "Transformer", "prerequisite"]],
    "forbidden": [["Faraday's law", "Magnetic flux", "prerequisite"],
                  ["Transformer", "Faraday's law", "prerequisite"]],
}}


# --- concepts ---------------------------------------------------------------

async def test_concepts_green():
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(GOOD_NODES)], _scenario(CONCEPT_EXPECT)))
    assert res.passed, res.details
    assert res.metrics["concepts_missing"] == 0.0


async def test_concepts_red_on_missing():
    res = await run_check(get_check("concepts"),
                          _ctx([_snap([FLUX, FARADAY])], _scenario(CONCEPT_EXPECT)))
    assert not res.passed
    assert any("missing concept 'Transformer'" in d for d in res.details)


async def test_concepts_red_on_duplicate_and_reports_unmatched():
    """(a)1/(a)2: the tmp- hole and the dead jaccard layer both surface as two
    live nodes for one concept."""
    nodes = GOOD_NODES + [_node("4", "Faraday's law of induction"),
                          _node("5", "Totally Unrelated Thing")]
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(nodes)], _scenario(CONCEPT_EXPECT)))
    assert not res.passed
    assert any("matched 2 live nodes" in d for d in res.details)
    # The line that lets a reader tell a real bug from a stale alias.
    assert any("Totally Unrelated Thing" in d and "unmatched" in d for d in res.details)


async def test_concepts_red_on_normalized_duplicate():
    """no_duplicates is absolute, not a rate: `dedup`'s C(n,2) denominator lets 18
    duplicate pairs through at 28 nodes."""
    nodes = GOOD_NODES + [_node("4", "transformers")]  # normalizes to "transformer"
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(nodes)], _scenario(CONCEPT_EXPECT)))
    assert not res.passed
    assert any("share normalized label" in d for d in res.details)
    assert res.metrics["duplicate_label_groups"] == 1.0


async def test_concepts_ignores_forgotten():
    nodes = [FLUX, FARADAY, TRANSFORMER, _node("9", "Transformer", forgotten="2026-01-01")]
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(nodes)], _scenario(CONCEPT_EXPECT)))
    assert res.passed, res.details


# --- edges ------------------------------------------------------------------

async def test_edges_green():
    res = await run_check(get_check("edges"),
                          _ctx([_snap(GOOD_NODES, GOOD_EDGES)], _scenario(EDGE_EXPECT)))
    assert res.passed, res.details
    assert res.metrics["edges_expected"] == 2.0


async def test_edges_red_on_missing_required():
    res = await run_check(get_check("edges"),
                          _ctx([_snap(GOOD_NODES, GOOD_EDGES[:1])], _scenario(EDGE_EXPECT)))
    assert not res.passed
    assert any("missing \"Faraday's law\" --prerequisite--> 'Transformer'" in d
               for d in res.details)


async def test_edges_red_on_reversed_direction():
    """THE direction-churn test. keeper.py:191 adopts the proposal's direction on
    upgrade, so a later wrong proposal silently flips a settled edge. A required-only
    check would pass here — the reversed edge is caught solely by `forbidden`."""
    reversed_edges = [{"source": "2", "target": "1", "type": "prerequisite", "weight": 1.0},
                      {"source": "2", "target": "3", "type": "prerequisite", "weight": 1.0}]
    res = await run_check(get_check("edges"),
                          _ctx([_snap(GOOD_NODES, reversed_edges)], _scenario(EDGE_EXPECT)))
    assert not res.passed
    assert any("FORBIDDEN edge present" in d for d in res.details)
    assert any("missing 'Magnetic flux'" in d for d in res.details)


async def test_edges_red_when_both_directions_present():
    """Churn can leave BOTH directions in the graph. `required` is satisfied, so
    only `forbidden` catches it. This is why forbidden exists."""
    both = GOOD_EDGES + [{"source": "2", "target": "1", "type": "prerequisite", "weight": 1.0}]
    res = await run_check(get_check("edges"),
                          _ctx([_snap(GOOD_NODES, both)], _scenario(EDGE_EXPECT)))
    assert not res.passed
    assert any("FORBIDDEN edge present" in d for d in res.details)


async def test_edges_wrong_type_is_not_a_match():
    weak = [{"source": "1", "target": "2", "type": "relates_to", "weight": 1.0},
            {"source": "2", "target": "3", "type": "prerequisite", "weight": 1.0}]
    res = await run_check(get_check("edges"),
                          _ctx([_snap(GOOD_NODES, weak)], _scenario(EDGE_EXPECT)))
    assert not res.passed
    assert any("missing 'Magnetic flux' --prerequisite--> \"Faraday's law\"" in d
               for d in res.details)


async def test_edges_reports_concept_gap_not_phantom_edge_failure():
    """A missing concept must not read as an edge bug — that sends an agent hunting
    in the Keeper's edge code when the real problem is upstream (or a stale alias)."""
    res = await run_check(get_check("edges"),
                          _ctx([_snap([FLUX, FARADAY], GOOD_EDGES)], _scenario(EDGE_EXPECT)))
    assert not res.passed
    assert any("concept(s) absent: ['Transformer']" in d for d in res.details)


async def test_edges_forbidden_absent_concept_is_not_a_failure():
    """If a concept doesn't exist, its forbidden edge can't either. Not a failure."""
    expect = {"edges": {"required": [],
                        "forbidden": [["Transformer", "Faraday's law", "prerequisite"]]}}
    res = await run_check(get_check("edges"),
                          _ctx([_snap([FLUX, FARADAY], [])], _scenario(expect)))
    assert res.passed, res.details


# --- abstention -------------------------------------------------------------

ABSTAIN = {"abstention": ["AC Circuits", "LC Oscillations", "Maxwell's Equations"]}


async def test_abstention_green():
    res = await run_check(get_check("abstention"),
                          _ctx([_snap(GOOD_NODES)], _scenario(ABSTAIN)))
    assert res.passed, res.details
    assert res.metrics["abstention_targets"] == 3.0


async def test_abstention_red_on_hallucination():
    """Every target is a label run edb608f6 actually produced from a scenario whose
    intents never mentioned it. With a frozen transcript the student cannot drift,
    so these can only come from the extractor's own weights."""
    nodes = GOOD_NODES + [_node("4", "AC Circuits (RLC Impedance)")]
    res = await run_check(get_check("abstention"),
                          _ctx([_snap(nodes)], _scenario(ABSTAIN)))
    assert not res.passed
    assert any("hallucinated 'AC Circuits'" in d for d in res.details)
    assert res.metrics["hallucinated_concepts"] == 1.0


async def test_abstention_red_even_when_forgotten():
    """Decaying a fabrication away doesn't make it acceptable — the extractor still
    invented it. Deliberately checks ALL nodes, not just live ones."""
    nodes = GOOD_NODES + [_node("4", "LC Oscillations", forgotten="2026-01-01")]
    res = await run_check(get_check("abstention"),
                          _ctx([_snap(nodes)], _scenario(ABSTAIN)))
    assert not res.passed
    assert any("forgotten" in d for d in res.details)


# --- knowledge_update -------------------------------------------------------

MASTERY_EXPECT = {"mastery": [
    {"concept": "Lenz's law", "after_session": 1, "max": 0.5},
    {"concept": "Lenz's law", "after_session": 2, "increased_from_session": 1},
]}


def _lenz_snaps(m1, m2):
    return [_snap([_node("1", "Lenz's law", mastery=0.2)], session=0),
            _snap([_node("1", "Lenz's law", mastery=m1)], session=1),
            _snap([_node("1", "Lenz's law", mastery=m2)], session=2)]


async def test_knowledge_update_green():
    res = await run_check(get_check("knowledge_update"),
                          _ctx(_lenz_snaps(0.3, 0.8), _scenario(MASTERY_EXPECT)))
    assert res.passed, res.details
    assert res.metrics["mastery_expectations"] == 2.0


async def test_knowledge_update_red_when_correction_never_lands():
    """THE misconception test. multi-session-em.yaml is built around a
    misconception the tutor corrects across three sessions, and nothing ever
    asserted the correction reaches the graph."""
    res = await run_check(get_check("knowledge_update"),
                          _ctx(_lenz_snaps(0.3, 0.3), _scenario(MASTERY_EXPECT)))
    assert not res.passed
    assert any("did not increase" in d and "correction never reached" in d
               for d in res.details)


async def test_knowledge_update_red_on_max_violation():
    """Misconception held in s1 -> mastery must be low. High mastery means the
    graph believes a wrong answer was right."""
    res = await run_check(get_check("knowledge_update"),
                          _ctx(_lenz_snaps(0.9, 0.95), _scenario(MASTERY_EXPECT)))
    assert not res.passed
    assert any("above max" in d for d in res.details)


async def test_knowledge_update_red_on_min_violation():
    expect = {"mastery": [{"concept": "Ohm's law", "after_session": 0, "min": 0.6}]}
    snaps = [_snap([_node("1", "Ohm's law", mastery=0.1)])]
    res = await run_check(get_check("knowledge_update"), _ctx(snaps, _scenario(expect)))
    assert not res.passed
    assert any("below min" in d for d in res.details)


async def test_knowledge_update_red_on_null_mastery():
    """A data bug must fail, never pass. Coercing None to 0.0 would satisfy a
    `max: 0.5` expectation — the trap lifecycle.py documents for salience."""
    expect = {"mastery": [{"concept": "Lenz's law", "after_session": 0, "max": 0.5}]}
    snaps = [_snap([_node("1", "Lenz's law", mastery=None)])]
    res = await run_check(get_check("knowledge_update"), _ctx(snaps, _scenario(expect)))
    assert not res.passed
    assert any("mastery=None" in d and "not a pass" in d for d in res.details)


async def test_knowledge_update_red_on_absent_concept():
    expect = {"mastery": [{"concept": "Lenz's law", "after_session": 0, "max": 0.5}]}
    snaps = [_snap([_node("1", "Something Else")])]
    res = await run_check(get_check("knowledge_update"), _ctx(snaps, _scenario(expect)))
    assert not res.passed
    assert any("absent after session 0" in d for d in res.details)
    assert any("unmatched labels" in d for d in res.details)


# --- cross-type duplicates --------------------------------------------------

async def test_concepts_red_on_cross_type_duplicate():
    """Observed on run a2b4c404: the graph held BOTH [conc] "Faraday's law" and
    [goal] "Faraday's law". _resolve opens every comparison with
    `if w.node.type != cand_type: continue`, so it can NEVER merge across type —
    no threshold reaches this. The phantoms are not inert either: the goal-typed
    ones carried 4 of that run's 9 edges, including a backwards one.
    """
    nodes = GOOD_NODES + [_node("4", "Faraday's law", ntype="goal")]
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(nodes)], _scenario(CONCEPT_EXPECT)))
    assert not res.passed
    assert any("multiple node types" in d and "['concept', 'goal']" in d
               for d in res.details)
    assert res.metrics["cross_type_duplicates"] == 1.0


async def test_concepts_green_when_types_are_distinct():
    """A preference and a concept with genuinely different labels must not trip it."""
    nodes = GOOD_NODES + [_node("4", "Short bullet-point answers", ntype="preference")]
    res = await run_check(get_check("concepts"),
                          _ctx([_snap(nodes)], _scenario(CONCEPT_EXPECT)))
    assert res.passed, res.details
    assert res.metrics["cross_type_duplicates"] == 0.0


# --- preferences / goals ----------------------------------------------------

PREF_EXPECT = {
    "preferences": {"required": ["Short bullet-point answers"],
                    "forbidden": ["Hard problems"]},
    "goals": {"required": ["Pass the electromagnetism midterm"]},
}
PREF_NODES = [_node("1", "Short bullet-point answers", ntype="preference"),
              _node("2", "Pass the electromagnetism midterm", ntype="goal")]


async def test_preferences_green():
    res = await run_check(get_check("preferences"),
                          _ctx([_snap(PREF_NODES)], _scenario(PREF_EXPECT)))
    assert res.passed, res.details
    assert res.metrics["live_preferences"] == 1.0 and res.metrics["live_goals"] == 1.0


async def test_preferences_red_on_missing():
    res = await run_check(get_check("preferences"),
                          _ctx([_snap(PREF_NODES[:1])], _scenario(PREF_EXPECT)))
    assert not res.passed
    assert any("missing goal" in d for d in res.details)


async def test_preferences_red_on_transient_request_minted():
    """_resolve has no reject path — every candidate becomes a node or merges. And
    an _resolve-level NOOP would NOT catch this: a transient request has no similar
    existing node, so cosine is low, so it never enters the reflector band. This is
    a quality judgement, not a similarity one; the fix is in the prompt."""
    nodes = PREF_NODES + [_node("3", "Hard problems", ntype="preference")]
    res = await run_check(get_check("preferences"),
                          _ctx([_snap(nodes)], _scenario(PREF_EXPECT)))
    assert not res.passed
    assert any("transient request minted as a preference" in d for d in res.details)


async def test_preferences_ignores_concept_typed_nodes():
    """A concept called 'Hard problems' is not a preference bug."""
    nodes = PREF_NODES + [_node("3", "Hard problems", ntype="concept")]
    res = await run_check(get_check("preferences"),
                          _ctx([_snap(nodes)], _scenario(PREF_EXPECT)))
    assert res.passed, res.details
