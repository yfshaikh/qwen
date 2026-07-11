"""EngramHost lifecycle + DisabledEngram null-object semantics (E1, E2)."""
from engram.core.engram import Engram
from engram.host import DisabledEngram, EngramHost
from engram.core.models import LearningEvent
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _eng():
    return Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=8))


# --- E1: disabled-mode table -------------------------------------------------

async def test_disabled_engram_verb_table():
    d = DisabledEngram()
    assert d.enabled is False
    assert (await d.recall("L", "q")).text_block == ""
    assert (await d.recall("L", "q")).subgraph == {"nodes": [], "edges": []}
    gv = await d.graph("L")
    assert gv.nodes == [] and gv.edges == []
    assert await d.audit("L") == []
    assert await d.events("L") == []
    assert await d.health() is False
    rep = await d.consolidate("L")
    assert rep.skipped is True and rep.learner_id == "L"
    out = await d.repair_merges("L")
    assert out == {"merged": 0, "pairs": [], "skipped": True}
    # voice passthroughs are also null (a disabled host must never AttributeError)
    assert await d.create_voice_session("L") == ""
    assert await d.list_voice_sessions("L") == []
    assert await d.list_voice_turns("s") == []
    await d.end_voice_session("s")
    assert await d.append_voice_turn("s", "L", "user", "hi") == ""
    # ingest is a silent no-op, never raises
    await d.ingest([LearningEvent(learner_id="L", type="utterance", text="hi")])


# --- E2: lifecycle -----------------------------------------------------------

async def test_start_success_and_idempotent():
    host = EngramHost(_eng())
    assert await host.start() is True
    assert await host.start() is True  # idempotent
    assert host.enabled and host.memory.enabled


async def test_construction_never_raises_failure_latches():
    calls = {"n": 0}

    class Boom:
        @staticmethod
        def from_env(**kw):
            calls["n"] += 1
            raise RuntimeError("missing config")

    host = EngramHost.from_env(database_url="x")   # must not raise here
    host._engram_factory = Boom.from_env           # test seam (see impl)
    assert await host.start() is False
    assert await host.start() is False
    assert calls["n"] == 1                          # latched, no retry storm
    assert host.enabled is False
    assert isinstance(host.memory, DisabledEngram)


async def test_connect_failure_disables():
    eng = _eng()

    async def bad_connect():
        raise RuntimeError("pool down")

    eng.connect = bad_connect  # type: ignore[method-assign]
    host = EngramHost(eng)
    assert await host.start() is False
    assert isinstance(host.memory, DisabledEngram)


async def test_aclose_then_start_restarts():
    host = EngramHost(_eng())
    assert await host.start() is True
    await host.aclose()
    assert host.enabled is False
    assert await host.start() is True  # E2: restart allowed


async def test_context_manager():
    async with EngramHost(_eng()) as host:
        assert host.enabled
    assert host.enabled is False


# --- E3: consolidate_soon ----------------------------------------------------

class _SlowConsolidateEngram:
    enabled = True

    def __init__(self):
        self.calls: list[str] = []
        self.gate = __import__("asyncio").Event()

    async def connect(self): ...
    async def aclose(self): ...

    async def consolidate(self, learner_id: str):
        self.calls.append(learner_id)
        await self.gate.wait()
        from engram.core.consolidation import ConsolidationReport
        return ConsolidationReport(learner_id=learner_id)


async def test_consolidate_soon_coalesces_burst():
    import asyncio
    eng = _SlowConsolidateEngram()
    host = EngramHost(eng)
    await host.start()
    for _ in range(10):
        host.consolidate_soon("L")
    await asyncio.sleep(0)                      # let the task start
    assert host.is_consolidating("L") is True
    assert eng.calls == ["L"]                   # one in flight
    eng.gate.set()
    for _ in range(20):
        await asyncio.sleep(0)
        if not host.is_consolidating("L"):
            break
    assert eng.calls == ["L", "L"]              # 10 calls -> exactly 2 runs
    assert host.is_consolidating("L") is False
    await host.aclose()


async def test_consolidate_soon_learner_isolation_and_errors(caplog):
    import asyncio

    class _Boom(_SlowConsolidateEngram):
        async def consolidate(self, learner_id: str):
            self.calls.append(learner_id)
            raise RuntimeError("keeper down")

    eng = _Boom()
    host = EngramHost(eng)
    await host.start()
    host.consolidate_soon("A")
    assert host.is_consolidating("B") is False   # isolation
    for _ in range(10):
        await asyncio.sleep(0)
    assert host.is_consolidating("A") is False   # error path clears the flag
    assert any("consolidation failed" in r.message.lower() for r in caplog.records)
    await host.aclose()


async def test_aclose_cancels_inflight_consolidation():
    import asyncio
    eng = _SlowConsolidateEngram()               # gate never set
    host = EngramHost(eng)
    await host.start()
    host.consolidate_soon("L")
    await asyncio.sleep(0)
    await host.aclose()                          # must not hang
    assert host.is_consolidating("L") is False


# --- E4: log builders ---------------------------------------------------------

async def test_log_turn_builds_standard_pair():
    host = EngramHost(_eng())
    await host.start()
    ok = await host.log_turn("L", user_text="what is flux?",
                             tutor_reply="flux is...", refs={"lesson_id": "x"})
    assert ok is True
    events = await host.memory.storage.get_pending_events("L")
    assert [e.type for e in events] == ["utterance", "tutor_explanation"]
    assert events[0].refs == {"lesson_id": "x"}
    await host.aclose()


async def test_log_turn_blank_sides_skipped():
    host = EngramHost(_eng())
    await host.start()
    assert await host.log_turn("L", user_text="  ", tutor_reply=None) is False
    assert await host.log_turn("L", user_text="hi", tutor_reply="   ") is True
    events = await host.memory.storage.get_pending_events("L")
    assert [e.type for e in events] == ["utterance"]   # blank reply skipped
    await host.aclose()


async def test_log_quiz_and_note_signals():
    host = EngramHost(_eng())
    await host.start()
    assert await host.log_quiz("L", "limits quiz", correct=False, mastery=0.2)
    assert await host.log_note("L", "prefers analogies")
    events = await host.memory.storage.get_pending_events("L")
    assert events[0].type == "quiz_result"
    assert events[0].signals == {"correct": False, "mastery": 0.2}
    assert events[1].type == "note"
    await host.aclose()


async def test_log_disabled_and_failure_return_false(caplog):
    host = EngramHost.from_env(database_url="x")
    host._engram_factory = lambda **kw: (_ for _ in ()).throw(RuntimeError("no"))
    await host.start()
    assert await host.log_turn("L", user_text="hi") is False  # disabled: no raise
