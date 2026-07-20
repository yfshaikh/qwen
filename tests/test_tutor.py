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


async def test_turn_reads_history_turns_from_settings(monkeypatch):
    # A non-default ENGRAM_RECALL_HISTORY_TURNS must reach the tutor's turn
    # limit. Exercises the real env -> Settings -> configs_from_settings ->
    # RecallConfig -> Engram.history_turns -> Tutor chain (storage/llm/embedder
    # are fakes so `turn()` does no real I/O, but the config plumbing is the
    # genuine `runtime.factory` mapping, not a hand-built RecallConfig).
    from engram.app.config import Settings
    from engram.runtime.factory import configs_from_settings

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://engram:engram@localhost:5432/engram")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "m")
    monkeypatch.setenv("ENGRAM_MODEL_EXTRACTOR", "m")
    monkeypatch.setenv("ENGRAM_MODEL_REFLECTOR", "m")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "m")
    monkeypatch.setenv("ENGRAM_RECALL_HISTORY_TURNS", "2")
    settings = Settings(_env_file=None)
    recall, keeper = configs_from_settings(settings)

    llm = FakeLLM(canned_text="ok")
    eng = Engram(storage=FakeStorage(), llm=llm, embedder=FakeEmbedder(dim=8),
                 settings=settings, recall=recall, keeper=keeper)
    messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "m2"},
        {"role": "user", "content": "m3"},
        {"role": "assistant", "content": "m4"},
        {"role": "user", "content": "m5"},
    ]
    [f async for f in Tutor(eng).turn("a", messages)]

    _, sent = llm.stream_calls[0]
    # 2 system messages (prefix + memory block) + last 2 conversation turns
    # (recall_history_turns=2, not the old hardcoded 10 which would keep all 5).
    assert len(sent) == 4
    assert [m.content for m in sent[-2:]] == ["m4", "m5"]


def test_system_prefix_directs_needs_attention():
    from engram.tutor.prompt import SYSTEM_PREFIX
    assert "Needs attention" in SYSTEM_PREFIX


def test_voice_system_directs_needs_attention():
    from engram.voice.prompt import SYSTEM
    assert "Needs attention" in SYSTEM
