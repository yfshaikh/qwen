import pytest

from engram.adapters.storage.postgres import PostgresStorage


async def test_health_false_before_connect(database_url):
    storage = PostgresStorage(database_url)
    assert await storage.health() is False


async def test_health_true_after_connect(database_url):
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        assert await storage.health() is True
    finally:
        await storage.close()


async def test_phase1_methods_not_yet_implemented(database_url):
    from engram.core.models import LearningEvent

    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        with pytest.raises(NotImplementedError):
            await storage.insert_event(LearningEvent(learner_id="a", type="utterance"))
    finally:
        await storage.close()
