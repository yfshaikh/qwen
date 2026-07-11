import pytest

from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from engram.tutor.tutor import Tutor
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _engram(canned="A limit is the value a function approaches."):
    return Engram(storage=FakeStorage(), llm=FakeLLM(canned_text=canned),
                  embedder=FakeEmbedder(dim=1024))


async def test_turn_emits_context_deltas_saved_done():
    eng = _engram()
    await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Limits",
             salience=0.9, embedding=[1.0] * 1024)
    )
    frames = [f async for f in Tutor(eng).turn("a", [{"role": "user", "content": "limits?"}])]
    kinds = [k for k, _ in frames]

    assert kinds[0] == "context"
    assert "Limits" in frames[0][1]["text_block"]
    assert "delta" in kinds
    reply = "".join(d["text"] for k, d in frames if k == "delta")
    assert reply == "A limit is the value a function approaches."
    saved = next(d for k, d in frames if k == "saved")
    assert [e["type"] for e in saved["events"]] == ["utterance", "tutor_explanation"]
    assert kinds[-1] == "done"
    assert frames[-1][1]["reply"] == reply
    # events actually written for later consolidation
    assert [e.type for e in eng.storage.events] == ["utterance", "tutor_explanation"]


async def test_turn_empty_memory_still_works():
    eng = _engram(canned="hi")
    frames = [f async for f in Tutor(eng).turn("new", [{"role": "user", "content": "hello"}])]
    assert frames[0][0] == "context"
    assert frames[0][1]["text_block"] == ""  # no nodes → empty block
    assert any(k == "done" for k, _ in frames)


async def test_turn_rejects_non_user_last_turn():
    eng = _engram()
    with pytest.raises(ValueError):
        [f async for f in Tutor(eng).turn("a", [{"role": "assistant", "content": "hi"}])]


async def test_turn_rejects_bad_input():
    eng = _engram()
    bad = [
        ("", [{"role": "user", "content": "x"}]),   # empty learner_id
        ("a", []),                                  # no messages
        ("a", [{"role": "user"}]),                  # missing content
        ("a", [{"role": "user", "content": ""}]),   # empty content
    ]
    for learner_id, messages in bad:
        with pytest.raises(ValueError):
            [f async for f in Tutor(eng).turn(learner_id, messages)]


async def test_turn_empty_reply_saves_only_utterance():
    eng = _engram(canned="")  # model streams nothing
    frames = [f async for f in Tutor(eng).turn("a", [{"role": "user", "content": "hi"}])]
    saved = next(d for k, d in frames if k == "saved")
    assert [e["type"] for e in saved["events"]] == ["utterance"]  # no empty tutor_explanation
    assert [e.type for e in eng.storage.events] == ["utterance"]
    assert frames[-1][1]["reply"] == ""


def test_system_prefix_directs_needs_attention():
    from engram.tutor.prompt import SYSTEM_PREFIX
    assert "Needs attention" in SYSTEM_PREFIX


def test_voice_system_directs_needs_attention():
    from engram.voice.prompt import SYSTEM
    assert "Needs attention" in SYSTEM
