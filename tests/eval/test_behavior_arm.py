from engram.core.engram import Engram
from engram.eval.arms import TurnRecord, format_baseline_context, run_behavior_arm
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def test_format_baseline_context_takes_last_n():
    hist = [{"role": "user", "content": f"m{i}"} for i in range(12)]
    ctx = format_baseline_context(hist, n=3)
    assert "m11" in ctx and "m9" in ctx and "m8" not in ctx


async def test_behavior_arm_baseline_records_replies():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text="REPLY"), embedder=FakeEmbedder())
    recs = await run_behavior_arm(eng, ["hi", "again"], "eval:x:1", "baseline")
    assert [r.query for r in recs] == ["hi", "again"]
    assert all(r.reply == "REPLY" for r in recs)
    # second turn's baseline context includes the first exchange
    assert "hi" in recs[1].context


async def test_behavior_arm_on_uses_recall(monkeypatch):
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text="R"), embedder=FakeEmbedder())
    recs = await run_behavior_arm(eng, ["q"], "eval:x:1", "on")
    assert isinstance(recs[0], TurnRecord)
    # recall against an empty graph yields an empty context block, not a crash
    assert recs[0].context == ""
