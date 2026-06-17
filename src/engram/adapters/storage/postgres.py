"""asyncpg-backed StoragePort. Phase 0: only `health()` has a real body."""

from __future__ import annotations

import asyncpg

from engram.core.models import LearningEvent, Node


class PostgresStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        # Small pool — Phase 0. Phases 1+ will tune sizing.
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1")
                if val != 1:
                    return False
                exists = await conn.fetchval(
                    "SELECT to_regclass('public.engram_nodes') IS NOT NULL"
                )
                return bool(exists)
        except Exception:
            return False

    async def insert_event(self, e: LearningEvent) -> str:
        raise NotImplementedError("Phase 1")

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        raise NotImplementedError("Phase 1")
