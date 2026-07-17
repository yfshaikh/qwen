import pytest

from engram.core.extraction import (
    _SYSTEM,
    Extraction,
    ExtractionError,
    build_extraction_messages,
    filter_provenance,
    parse_extraction,
)
from engram.core.models import LearningEvent

VALID = """
{
  "concepts": [
    {"label": "Limits", "summary": "approach",
     "evidence": [{"kind": "quiz_correct", "content": "got it", "importance": 0.8}]}
  ],
  "preferences": [{"label": "worked examples", "summary": null, "evidence": []}],
  "goals": [],
  "relations": [{"source_label": "Limits", "target_label": "Derivatives", "type": "prerequisite"}]
}
"""


def test_parse_valid_flattens_nodes_with_types():
    ex = parse_extraction(VALID)
    types = sorted(n.type for n in ex.nodes)
    assert types == ["concept", "preference"]
    limits = next(n for n in ex.nodes if n.label == "Limits")
    assert limits.evidence[0].kind == "quiz_correct"
    assert ex.relations[0].type == "prerequisite"


def test_parse_skips_invalid_enums_but_keeps_valid():
    text = """
    {"concepts": [{"label": "A", "summary": null,
       "evidence": [{"kind": "bogus_kind", "content": "x"},
                    {"kind": "struggle", "content": "y"}]}],
     "preferences": [], "goals": [],
     "relations": [{"source_label": "A", "target_label": "B", "type": "bogus_rel"}]}
    """
    ex = parse_extraction(text)
    assert [e.kind for e in ex.nodes[0].evidence] == ["struggle"]  # bogus dropped
    assert ex.relations == []  # bogus relation dropped


def test_parse_coerces_non_numeric_importance_and_mastery():
    # The live LLM sometimes returns qualitative words ("high"/"low") for the
    # numeric importance/mastery fields. These must become float-or-None before
    # they reach the float4 DB columns — never a raw string.
    text = """
    {"concepts": [{"label": "Limits", "summary": null,
       "evidence": [
         {"kind": "quiz_correct", "content": "a", "importance": "high"},
         {"kind": "struggle", "content": "b", "importance": "0.7", "mastery": "low"},
         {"kind": "demonstrated", "content": "c", "importance": 0.9, "mastery": 0.5}
       ]}],
     "preferences": [], "goals": [], "relations": []}
    """
    ev = parse_extraction(text).nodes[0].evidence
    assert ev[0].importance is None  # "high" -> None, not the raw string
    assert ev[1].importance == 0.7  # numeric string -> float
    assert ev[1].mastery is None  # "low" -> None
    assert ev[2].importance == 0.9 and ev[2].mastery == 0.5  # numbers kept
    assert all(
        e.importance is None or isinstance(e.importance, float) for e in ev
    )


def test_parse_malformed_raises():
    with pytest.raises(ExtractionError):
        parse_extraction("not json")
    with pytest.raises(ExtractionError):
        parse_extraction('{"concepts": "notalist"}')


def test_build_messages_includes_events_and_signals():
    events = [
        LearningEvent(learner_id="a", type="quiz_result", text="2+2", signals={"correct": True})
    ]
    msgs = build_extraction_messages(events)
    assert msgs[0].role == "system"
    blob = msgs[-1].content
    assert "quiz_result" in blob and "correct" in blob


def test_parse_extraction_reads_concept_importance():
    from engram.core.extraction import parse_extraction
    out = parse_extraction(
        '{"concepts": [{"label": "Flux", "summary": "s", "importance": 0.8,'
        ' "evidence": []}], "preferences": [], "goals": [], "relations": []}')
    assert out.nodes[0].importance == 0.8


def test_parse_extraction_coerces_bad_importance_to_none():
    from engram.core.extraction import parse_extraction
    out = parse_extraction(
        '{"concepts": [{"label": "Flux", "summary": "s", "importance": "high",'
        ' "evidence": []}], "preferences": [], "goals": [], "relations": []}')
    assert out.nodes[0].importance is None


VOCAB = [("c1", "Slope"), ("c2", "Slope-intercept form")]


def _ev(text, type="user_message", signals=None):
    return LearningEvent(learner_id="alice", type=type, text=text, signals=signals or {})


def test_open_mode_prompt_unchanged():
    events = [_ev("what is slope?")]
    a = build_extraction_messages(events)
    b = build_extraction_messages(events, None)
    c = build_extraction_messages(events, [])
    assert a[0].content is _SYSTEM and b[0].content is _SYSTEM and c[0].content is _SYSTEM
    assert a[1].content == b[1].content == c[1].content
    assert a[1].content.startswith("Events:\n")
    assert "CONCEPTS" not in a[1].content


def test_known_labels_anchor_open_prompt():
    events = [_ev("tell me about induction")]
    known = [("concept", "electromagnetic induction"), ("goal", "pass the midterm")]
    msgs = build_extraction_messages(events, None, known)
    # still open mode: same calibrated system prompt, events still present
    assert msgs[0].content is _SYSTEM
    assert "KNOWN NODES" in msgs[1].content
    assert "  concept: electromagnetic induction" in msgs[1].content
    assert "  goal: pass the midterm" in msgs[1].content
    assert "reuse the EXACT label" in msgs[1].content
    assert "Events:\n" in msgs[1].content


def test_known_labels_empty_keeps_prompt_byte_identical():
    events = [_ev("what is slope?")]
    assert (build_extraction_messages(events, None, [])[1].content
            == build_extraction_messages(events)[1].content)
    assert "KNOWN NODES" not in build_extraction_messages(events)[1].content


def test_vocabulary_wins_over_known():
    # ontology mode is closed; the known-labels anchor must not leak into it
    msgs = build_extraction_messages(
        [_ev("what is slope?")], VOCAB, [("concept", "Slope")])
    assert "KNOWN NODES" not in msgs[1].content and "CONCEPTS" in msgs[1].content


def test_known_catalog_order_is_deterministic():
    events = [_ev("x")]
    a = build_extraction_messages(events, None, [("concept", "B"), ("concept", "A")])
    b = build_extraction_messages(events, None, [("concept", "A"), ("concept", "B")])
    assert a[1].content == b[1].content


def test_closed_prompt_carries_catalog_and_forbids_relations():
    msgs = build_extraction_messages([_ev("what is slope?")], VOCAB)
    assert msgs[0].content is not _SYSTEM
    assert "c1" in msgs[1].content and "Slope" in msgs[1].content
    assert "Do NOT output a 'relations' key" in msgs[0].content


def test_closed_parse_accepts_concept_id():
    text = '{"concepts": [{"concept_id": "c1", "evidence": [{"kind": "quiz_correct"}]}]}'
    ext = parse_extraction(text, VOCAB)
    assert len(ext.nodes) == 1
    assert ext.nodes[0].external_id == "c1" and ext.nodes[0].label == "Slope"


def test_closed_parse_uses_ontology_label_not_model_echo():
    text = '{"concepts": [{"concept_id": "c1", "label": "SLOPE"}]}'
    ext = parse_extraction(text, VOCAB)
    assert ext.nodes[0].label == "Slope"


def test_closed_parse_falls_back_to_normalized_label():
    text = '{"concepts": [{"label": "slope"}]}'
    ext = parse_extraction(text, VOCAB)
    assert ext.nodes[0].external_id == "c1"


def test_closed_parse_drops_off_list_concept():
    text = '{"concepts": [{"label": "factoring cubics"}]}'
    ext = parse_extraction(text, VOCAB)
    assert ext.nodes == []
    assert any("factoring cubics" in d for d in ext.dropped)


def test_closed_parse_ignores_relations():
    text = ('{"concepts": [{"concept_id": "c1"}],'
            ' "relations": [{"source_label": "Slope", "target_label": "Slope-intercept form",'
            ' "type": "prerequisite"}]}')
    ext = parse_extraction(text, VOCAB)
    assert ext.relations == []


def test_closed_parse_keeps_preferences_and_goals():
    text = ('{"concepts": [], "preferences": [{"label": "bullet points"}],'
            ' "goals": [{"label": "score 700"}]}')
    ext = parse_extraction(text, VOCAB)
    kinds = {n.type: n for n in ext.nodes}
    assert "preference" in kinds and "goal" in kinds
    assert kinds["preference"].external_id is None


def test_filter_provenance_preserves_dropped():
    ext = Extraction(nodes=[], relations=[], dropped=["factoring cubics"])
    kept, _ = filter_provenance(ext, [_ev("hi")])
    assert kept.dropped == ["factoring cubics"]
