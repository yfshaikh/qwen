"""Voice-session persistence (host-layer): sessions and turns."""

from __future__ import annotations

from ._base import _Base


class _VoiceMixin(_Base):
    async def create_voice_session(self, learner_id: str) -> str:
        async with self._require_pool.acquire() as conn:
            sid = await conn.fetchval(
                "INSERT INTO engram_voice_sessions (learner_id) VALUES ($1) RETURNING id",
                learner_id,
            )
            return str(sid)

    async def end_voice_session(self, session_id: str) -> None:
        async with self._require_pool.acquire() as conn:
            await conn.execute(
                "UPDATE engram_voice_sessions SET ended_at = now() WHERE id = $1",
                session_id,
            )

    async def append_voice_turn(self, session_id, learner_id, role, text) -> str:
        async with self._require_pool.acquire() as conn:
            tid = await conn.fetchval(
                "INSERT INTO engram_voice_turns (session_id, learner_id, role, text)"
                " VALUES ($1,$2,$3,$4) RETURNING id",
                session_id, learner_id, role, text,
            )
            return str(tid)

    async def list_voice_sessions(self, learner_id: str, limit: int = 50) -> list[dict]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.id, s.started_at, s.ended_at,
                       count(t.id) AS turns
                FROM engram_voice_sessions s
                LEFT JOIN engram_voice_turns t ON t.session_id = s.id
                WHERE s.learner_id = $1
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT $2
                """,
                learner_id, limit,
            )
            return [{"id": str(r["id"]), "started_at": r["started_at"],
                     "ended_at": r["ended_at"], "turns": r["turns"]} for r in rows]

    async def list_voice_turns(self, session_id: str) -> list[dict]:
        async with self._require_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, role, text, ts FROM engram_voice_turns"
                " WHERE session_id = $1 ORDER BY ts",
                session_id,
            )
            return [{"id": str(r["id"]), "role": r["role"], "text": r["text"],
                     "ts": r["ts"]} for r in rows]
