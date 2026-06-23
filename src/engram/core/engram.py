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
    def __init__(
        self,
        storage: Any,
        llm: Any,
        embedder: Any,
        settings: Any = None,
        token_count: Any = None,
    ) -> None:
        from engram.core.tokens import heuristic_token_count

        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.settings = settings
        self._token_count = token_count or heuristic_token_count

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
        for e in events:
            if not e.learner_id or not e.type:
                raise ValueError("LearningEvent requires non-empty learner_id and type")
        await self.storage.insert_events(events)

    async def recall(
        self, learner_id: str, query: str, budget: int | None = None
    ) -> RecallResult:
        from engram.core.recall import Recall, RecallWeights

        s = self.settings
        if s is not None:
            weights = RecallWeights(
                s.recall_w_recency, s.recall_w_importance, s.recall_w_relevance
            )
            recall = Recall(
                self.storage, self.embedder, self._token_count, weights,
                seed_k=s.recall_seed_k, hops=s.recall_hops, fanout=s.recall_fanout,
            )
            budget = budget if budget is not None else s.recall_default_budget
        else:
            recall = Recall(
                self.storage, self.embedder, self._token_count, RecallWeights()
            )
            budget = budget if budget is not None else 800
        return await recall.run(learner_id, query, budget)

    async def consolidate(self, learner_id: str):
        from engram.core.keeper import Keeper, KeeperParams

        s = self.settings
        if s is not None:
            params = KeeperParams(
                tau_high=s.keeper_tau_high,
                tau_low=s.keeper_tau_low,
                ewma_alpha=s.keeper_ewma_alpha,
                salience_bump=s.keeper_salience_bump,
                prune_floor=s.keeper_prune_floor,
                decay=s.recall_decay,
            )
        else:
            params = KeeperParams()
        keeper = Keeper(self.storage, self.llm, self.embedder, params)
        return await keeper.consolidate(learner_id)

    async def audit(self, learner_id: str, since: Any = None, limit: int = 100) -> list[dict]:
        return await self.storage.get_audit(learner_id, since, limit)

    async def graph(self, learner_id: str, focus: str | None = None) -> GraphView:
        from engram.core.graph import build_graph

        return await build_graph(self.storage, learner_id, focus)

    # --- mem0-style aliases ---------------------------------------------
    # add -> ingest, search -> recall. Aliased to the same functions so a mem0
    # user is instantly productive; the canonical names carry the typed depth.
    add = ingest
    search = recall
