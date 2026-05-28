"""Live tests against the docker-compose pgvector container.

Bring it up first: `docker compose up -d db`.
"""

import pytest

from engram.adapters.storage.postgres import PostgresStorage


@pytest.mark.asyncio
async def test_health_true_against_live_db(database_url: str) -> None:
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        assert await storage.health() is True
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_health_false_when_db_unreachable() -> None:
    # Unused port; connection must fail fast and health() must return False.
    storage = PostgresStorage("postgresql://engram:engram@127.0.0.1:1/engram")
    # connect() may itself raise — that's fine; health() is the contract.
    try:
        await storage.connect()
    except Exception:
        pass
    assert await storage.health() is False


@pytest.mark.asyncio
async def test_phase_n_methods_raise_not_implemented(database_url: str) -> None:
    from engram.core.models import LearningEvent

    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        with pytest.raises(NotImplementedError, match="Phase 1"):
            await storage.insert_event(LearningEvent(learner_id="x", type="utterance"))
        with pytest.raises(NotImplementedError, match="Phase 1"):
            await storage.vector_search("x", [0.0] * 1024, 5)
    finally:
        await storage.close()
