import pytest

from engram.core.extraction import (
    ExtractionError,
    build_extraction_messages,
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
