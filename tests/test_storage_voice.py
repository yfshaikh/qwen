import pytest

from engram.adapters.storage.postgres import PostgresStorage


@pytest.fixture
async def store(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    yield s
    await s.delete_learner("voice-test")
    await s.close()


async def test_voice_session_roundtrip(store):
    sid = await store.create_voice_session("voice-test")
    await store.append_voice_turn(sid, "voice-test", "user", "hi")
    await store.append_voice_turn(sid, "voice-test", "assistant", "hello")
    await store.end_voice_session(sid)

    sessions = await store.list_voice_sessions("voice-test")
    assert sessions[0]["id"] == sid and sessions[0]["turns"] == 2
    turns = await store.list_voice_turns(sid)
    assert [t["role"] for t in turns] == ["user", "assistant"]
