import pytest

from engram.core.engram import Engram
from engram.core.models import LearningEvent
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _engram(healthy=True):
    return Engram(storage=FakeStorage(healthy=healthy), llm=FakeLLM(), embedder=FakeEmbedder())


async def test_health_delegates_to_storage():
    assert await _engram(healthy=True).health() is True
    assert await _engram(healthy=False).health() is False


async def test_memory_verbs_are_phase1_stubs():
    eng = _engram()
    with pytest.raises(NotImplementedError):
        await eng.ingest([LearningEvent(learner_id="a", type="utterance")])
    with pytest.raises(NotImplementedError):
        await eng.recall("a", "topic", 800)
    with pytest.raises(NotImplementedError):
        await eng.consolidate("a")
    with pytest.raises(NotImplementedError):
        await eng.graph("a")


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
