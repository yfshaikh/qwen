"""The Engram facade — the public, mem0-style API surface.

Phase 0 wires construction, env composition, lifecycle, and health. The four
memory verbs (ingest/recall/consolidate/graph) are stubs that Phases 1–2 fill.

Usage:
    eng = Engram.from_env()
    await eng.connect()
    await eng.add(events, learner_id="alice")       # alias for ingest()
    ctx = await eng.search("limits", learner_id="alice", budget=800)  # recall()
    await eng.aclose()
"""

from __future__ import annotations

from typing import Any

from engram.core.models import GraphView, LearningEvent, RecallResult


class Engram:
    def __init__(self, storage: Any, llm: Any, embedder: Any, settings: Any = None) -> None:
        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.settings = settings

    # --- construction & lifecycle ---------------------------------------

    @classmethod
    def from_env(cls, **settings_kwargs: Any) -> Engram:
        """Build a fully-wired Engram from environment/.env via Settings.

        Pass `_env_file=None` to ignore any on-disk .env (used in tests).
        Call `await connect()` afterwards to open the storage pool.
        """
        from engram.adapters.llm.openai_compatible import build_llm
        from engram.adapters.llm.openai_embedder import build_embedder
        from engram.adapters.storage.postgres import PostgresStorage
        from engram.app.config import Settings

        settings = Settings(**settings_kwargs)
        return cls(
            storage=PostgresStorage(settings.database_url),
            llm=build_llm(settings),
            embedder=build_embedder(settings),
            settings=settings,
        )

    async def connect(self) -> None:
        connect = getattr(self.storage, "connect", None)
        if callable(connect):
            await connect()

    async def aclose(self) -> None:
        close = getattr(self.storage, "close", None)
        if callable(close):
            await close()

    async def health(self) -> bool:
        return await self.storage.health()

    # --- memory verbs (Phase 1–2 bodies) --------------------------------

    async def ingest(self, events: list[LearningEvent]) -> None:
        raise NotImplementedError("Phase 1")

    async def recall(self, learner_id: str, query: str, budget: int) -> RecallResult:
        raise NotImplementedError("Phase 1")

    async def consolidate(self, learner_id: str) -> None:
        raise NotImplementedError("Phase 2")

    async def graph(self, learner_id: str, focus: str | None = None) -> GraphView:
        raise NotImplementedError("Phase 1")

    # --- mem0-style aliases ---------------------------------------------
    # add -> ingest, search -> recall. Aliased to the same functions so a mem0
    # user is instantly productive; the canonical names carry the typed depth.
    add = ingest
    search = recall
