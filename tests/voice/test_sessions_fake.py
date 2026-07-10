from tests.fakes import FakeStorage


async def test_session_lifecycle_and_listing():
    s = FakeStorage()
    sid = await s.create_voice_session("a")
    await s.append_voice_turn(sid, "a", "user", "hi")
    await s.append_voice_turn(sid, "a", "assistant", "hello")
    await s.end_voice_session(sid)

    sessions = await s.list_voice_sessions("a")
    assert len(sessions) == 1
    assert sessions[0]["id"] == sid and sessions[0]["ended_at"] is not None
    assert sessions[0]["turns"] == 2

    turns = await s.list_voice_turns(sid)
    assert [(t["role"], t["text"]) for t in turns] == [("user", "hi"), ("assistant", "hello")]


async def test_delete_learner_clears_sessions():
    s = FakeStorage()
    sid = await s.create_voice_session("a")
    await s.append_voice_turn(sid, "a", "user", "hi")
    await s.delete_learner("a")
    assert await s.list_voice_sessions("a") == []
