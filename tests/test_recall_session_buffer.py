"""Pending (un-consolidated) events surface in recall's text_block (#1)."""
from engram.core.models import LearningEvent, Node, NodeType
from engram.core.recall import Recall, RecallWeights
from engram.core.tokens import heuristic_token_count
from tests.fakes import FakeEmbedder, FakeStorage


def _recall(storage, **kw):
    return Recall(storage, FakeEmbedder(dim=8), heuristic_token_count,
                  RecallWeights(), **kw)


async def _seed(storage):
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="Limits", mastery=0.9,
        salience=0.5, embedding=[1.0] * 8))


async def test_pending_quiz_event_surfaces_before_consolidation():
    storage = FakeStorage()
    await _seed(storage)
    await storage.insert_event(LearningEvent(
        learner_id="L", type="quiz_result", text="quiz on Limits",
        signals={"correct": False}))
    res = await _recall(storage).run("L", "query", 800)
    assert "This session (not yet consolidated):" in res.text_block
    assert "quiz on Limits" in res.text_block
    assert "correct=False" in res.text_block


async def test_flag_off_no_buffer():
    storage = FakeStorage()
    await _seed(storage)
    await storage.insert_event(LearningEvent(
        learner_id="L", type="quiz_result", text="quiz on Limits",
        signals={"correct": False}))
    res = await _recall(storage, session_buffer=False).run("L", "query", 800)
    assert "not yet consolidated" not in res.text_block


async def test_plain_utterances_excluded_signal_utterances_included():
    storage = FakeStorage()
    await _seed(storage)
    await storage.insert_event(LearningEvent(
        learner_id="L", type="utterance", text="small talk"))
    await storage.insert_event(LearningEvent(
        learner_id="L", type="utterance", text="I keep confusing flux and field",
        signals={"confusion": True}))
    res = await _recall(storage).run("L", "query", 800)
    assert "small talk" not in res.text_block
    assert "confusing flux and field" in res.text_block


async def test_buffer_keeps_last_six_and_truncates_to_budget():
    storage = FakeStorage()
    await _seed(storage)
    for i in range(10):
        await storage.insert_event(LearningEvent(
            learner_id="L", type="note", text=f"note number {i}"))
    res = await _recall(storage).run("L", "query", 800)
    assert "note number 3" not in res.text_block  # only last 6
    assert "note number 9" in res.text_block
    # tiny budget: nodes may not fit, buffer must not blow past it either
    tiny = await _recall(storage).run("L", "query", 10)
    assert heuristic_token_count(tiny.text_block) <= 10


async def test_no_pending_events_no_header():
    storage = FakeStorage()
    await _seed(storage)
    res = await _recall(storage).run("L", "query", 800)
    assert "not yet consolidated" not in res.text_block
