import pytest

from engram.core.engram import Engram
from engram.core.models import LearningEvent
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _engram(healthy=True):
    return Engram(storage=FakeStorage(healthy=healthy), llm=FakeLLM(), embedder=FakeEmbedder())


async def test_health_delegates_to_storage():
    assert await _engram(healthy=True).health() is True
    assert await _engram(healthy=False).health() is False


async def test_remaining_verbs_are_later_phase_stubs():
    eng = _engram()
    with pytest.raises(NotImplementedError):
        await eng.graph("a")


async def test_ingest_appends_events():
    eng = _engram()
    await eng.ingest(
        [
            LearningEvent(learner_id="a", type="utterance", text="hi"),
            LearningEvent(learner_id="a", type="note", text="n"),
        ]
    )
    assert len(eng.storage.events) == 2


async def test_ingest_rejects_malformed_event_before_writing():
    eng = _engram()
    with pytest.raises(ValueError):
        await eng.ingest([LearningEvent(learner_id="", type="utterance")])
    assert eng.storage.events == []  # all-or-nothing


async def test_add_alias_ingests():
    eng = _engram()
    await eng.add([LearningEvent(learner_id="a", type="note", text="n")])
    assert len(eng.storage.events) == 1


async def test_recall_against_seeded_graph():
    from pathlib import Path

    from engram.adapters.seed import seed_graph

    eng = _engram()
    fixture = Path(__file__).parent / "fixtures" / "seed_basic.yaml"
    await seed_graph(eng.storage, eng.embedder, fixture)
    res = await eng.recall("alice", "limits", budget=800)
    assert "Limits" in res.text_block


async def test_consolidate_returns_report():
    import json

    from engram.core.models import LearningEvent

    eng = _engram()
    await eng.ingest([LearningEvent(learner_id="a", type="utterance", text="t")])
    eng.llm.canned_text = json.dumps(
        {"concepts": [{"label": "Limits", "summary": "s",
                       "evidence": [{"kind": "quiz_correct", "content": "ok"}]}],
         "preferences": [], "goals": [], "relations": []}
    )
    report = await eng.consolidate("a")
    assert report.nodes_created == 1
    assert len(eng.storage.nodes) == 1


async def test_consolidate_skipped_when_locked():
    eng = _engram()
    async with eng.storage.consolidation_lock("a"):
        report = await eng.consolidate("a")
    assert report.skipped is True


async def test_ingest_consolidate_recall_loop_live(database_url):
    import json
    import uuid

    from engram.adapters.storage.postgres import PostgresStorage
    from engram.core.engram import Engram
    from engram.core.models import LearningEvent
    from tests.fakes import FakeEmbedder, FakeLLM

    learner = f"t-{uuid.uuid4()}"
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        llm = FakeLLM(canned_text=json.dumps(
            {"concepts": [{"label": "Limits", "summary": "approach",
                           "evidence": [{"kind": "quiz_correct", "content": "ok"}]}],
             "preferences": [], "goals": [], "relations": []}
        ))
        eng = Engram(storage=storage, llm=llm, embedder=FakeEmbedder(dim=1024))
        await eng.ingest([LearningEvent(learner_id=learner, type="utterance", text="limit?")])
        report = await eng.consolidate(learner)
        assert report.nodes_created == 1
        # second run is a no-op (watermark)
        report2 = await eng.consolidate(learner)
        assert report2.processed_events == 0
        # recall now reads the Keeper-built graph
        res = await eng.recall(learner, "limits", budget=800)
        assert "Limits" in res.text_block
    finally:
        await storage.close()


async def test_mem0_aliases_point_at_canonical_verbs():
    eng = _engram()
    # add -> ingest, search -> recall: same bound underlying coroutine function.
    assert eng.add.__func__ is Engram.ingest
    assert eng.search.__func__ is Engram.recall


def test_from_env_wires_real_adapters(monkeypatch):
    env = {
        "OPENROUTER_API_KEY": "sk-or-test",
        "OPENAI_API_KEY": "sk-test",
        "DATABASE_URL": "postgresql://engram:engram@localhost:5432/engram",
        "ENGRAM_MODEL_TUTOR": "qwen/tutor",
        "ENGRAM_MODEL_EXTRACTOR": "qwen/extract",
        "ENGRAM_MODEL_REFLECTOR": "qwen/reflect",
        "ENGRAM_MODEL_EMBEDDER": "text-embedding-3-small",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    from engram.adapters.llm.openai_compatible import OpenAICompatibleLLM
    from engram.adapters.llm.openai_embedder import OpenAIEmbedder
    from engram.adapters.storage.postgres import PostgresStorage

    eng = Engram.from_env(_env_file=None)
    assert isinstance(eng.storage, PostgresStorage)
    assert isinstance(eng.llm, OpenAICompatibleLLM)
    assert isinstance(eng.embedder, OpenAIEmbedder)
