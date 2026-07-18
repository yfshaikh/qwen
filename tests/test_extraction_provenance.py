"""Preferences/goals must come from the learner's own words (#4)."""
from engram.core.extraction import (
    ExtractedEvidence,
    ExtractedNode,
    Extraction,
    filter_provenance,
)
from engram.core.models import LearningEvent


def _pref(label="No memorization", content="you don't need to memorize"):
    return ExtractedNode(type="preference", label=label, summary="s",
                         evidence=[ExtractedEvidence(kind="note", content=content)])


def _concept():
    return ExtractedNode(type="concept", label="Limits", summary="s",
                         evidence=[ExtractedEvidence(kind="explained",
                                                     content="you don't need to memorize")])


def test_tutor_only_batch_drops_preference_keeps_concept():
    events = [LearningEvent(learner_id="L", type="tutor_explanation",
                            text="Relax — you don't need to memorize the table.")]
    out, dropped = filter_provenance(Extraction(nodes=[_pref(), _concept()]), events)
    assert [n.label for n in out.nodes] == ["Limits"]
    assert dropped == ["No memorization"]


def test_learner_utterance_keeps_preference():
    events = [LearningEvent(learner_id="L", type="utterance",
                            text="honestly you don't need to memorize stuff to teach me")]
    out, dropped = filter_provenance(Extraction(nodes=[_pref()]), events)
    assert [n.label for n in out.nodes] == ["No memorization"]
    assert dropped == []


def test_mixed_batch_traces_evidence_to_tutor_and_drops():
    events = [
        LearningEvent(learner_id="L", type="utterance", text="what is a limit?"),
        LearningEvent(learner_id="L", type="tutor_explanation",
                      text="A limit is... you don't need to memorize this."),
    ]
    out, dropped = filter_provenance(Extraction(nodes=[_pref()]), events)
    assert dropped == ["No memorization"]


def test_untraceable_evidence_with_learner_events_keeps():
    events = [LearningEvent(learner_id="L", type="utterance", text="quiz me on flux")]
    out, dropped = filter_provenance(
        Extraction(nodes=[_pref(content="prefers visual analogies")]), events)
    assert dropped == []


def test_goal_type_also_filtered():
    g = ExtractedNode(type="goal", label="Ace exam", summary="s",
                      evidence=[ExtractedEvidence(kind="note", content="ace the exam")])
    events = [LearningEvent(learner_id="L", type="tutor_explanation",
                            text="With practice you will ace the exam!")]
    out, dropped = filter_provenance(Extraction(nodes=[g]), events)
    assert dropped == ["Ace exam"]
