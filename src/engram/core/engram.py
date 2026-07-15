"""The Engram facade — the public, mem0-style API surface.

Wires construction, env composition, lifecycle, and health, and implements
the four memory verbs (ingest/recall/consolidate/graph).

Usage:
    eng = Engram.from_env()
    await eng.connect()
    await eng.add(events, learner_id="alice")       # alias for ingest()
    ctx = await eng.search("limits", learner_id="alice", budget=800)  # recall()
    await eng.aclose()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engram.core.config import KeeperConfig, RecallConfig
from engram.core.models import AuditRow, GraphView, LearningEvent, RecallResult

if TYPE_CHECKING:
    from engram.core.keeper import Keeper


class Engram:
    enabled = True

    def __init__(
        self,
        storage: Any,
        llm: Any,
        embedder: Any,
        settings: Any = None,
        token_count: Any = None,
        now: Any = None,
        recall: RecallConfig | None = None,
        keeper: KeeperConfig | None = None,
    ) -> None:
        from engram.core.tokens import heuristic_token_count

        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.settings = settings
        self._token_count = token_count or heuristic_token_count
        self._now = now
        self._recall = recall or RecallConfig()
        self._keeper = keeper or KeeperConfig()

    @property
    def history_turns(self) -> int:
        """How many trailing conversation turns hosts should feed into a
        prompt. Domain knob — reads `RecallConfig`, never `settings`, so it
        works the same whether `Engram` was built via `from_env()` or
        constructed directly with an explicit `recall=RecallConfig(...)`."""
        return self._recall.history_turns

    # --- construction & lifecycle ---------------------------------------

    @classmethod
    def from_env(cls, now: Any = None, **settings_kwargs: Any) -> Engram:
        """Build a fully-wired Engram from environment/.env via Settings.

        Pass `_env_file=None` to ignore any on-disk .env (used in tests).
        Call `await connect()` afterwards to open the storage pool.

        Thin compatibility shim: the composition root lives in
        `engram.runtime.factory.from_env` (this package stays free of
        outward-facing wiring imports); this delegates so the public
        `Engram.from_env()` name Marfini and older callers use keeps working.
        """
        from engram.runtime.factory import from_env as _factory_from_env

        return _factory_from_env(now=now, **settings_kwargs)

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

        r = self._recall
        weights = RecallWeights(r.w_recency, r.w_importance, r.w_relevance)
        recall = Recall(
            self.storage, self.embedder, self._token_count, weights,
            seed_k=r.seed_k, hops=r.hops, fanout=r.fanout,
            session_buffer=r.session_buffer,
        )
        budget = budget if budget is not None else r.default_budget
        return await recall.run(learner_id, query, budget)

    def _make_keeper(self) -> Keeper:
        from engram.core.keeper import Keeper, KeeperParams

        k = self._keeper
        params = KeeperParams(
            tau_high=k.tau_high,
            tau_low=k.tau_low,
            ewma_alpha=k.ewma_alpha,
            salience_bump=k.salience_bump,
            prune_floor=k.prune_floor,
            decay=k.decay,
        )
        return Keeper(self.storage, self.llm, self.embedder, params, clock=self._now)

    async def consolidate(self, learner_id: str):
        keeper = self._make_keeper()
        return await keeper.consolidate(learner_id)

    async def repair_merges(self, learner_id: str) -> dict:
        """Retroactively merge duplicate nodes in an existing graph (#6)."""
        keeper = self._make_keeper()
        return await keeper.repair_merges(learner_id)

    async def audit(self, learner_id: str, since: Any = None, limit: int = 100) -> list[AuditRow]:
        rows = await self.storage.get_audit(learner_id, since, limit)
        return [AuditRow(
            id=str(r["id"]), op=r["op"], rationale=r.get("rationale"),
            model=r.get("model"), tokens=r.get("tokens"),
            cost=float(r["cost"]) if r.get("cost") is not None else None,
            ts=r["ts"],
        ) for r in rows]

    async def events(self, learner_id: str, limit: int = 200) -> list[LearningEvent]:
        """The raw event log for a learner (oldest-first). Hosts reconstruct chat
        history from this; the role/type mapping is a host concern, not core."""
        return await self.storage.get_events(learner_id, limit)

    async def graph(self, learner_id: str, focus: str | None = None) -> GraphView:
        from engram.core.graph import build_graph

        return await build_graph(self.storage, learner_id, focus)

    # --- voice sessions (host-layer passthroughs) -----------------------

    async def create_voice_session(self, learner_id: str) -> str:
        return await self.storage.create_voice_session(learner_id)

    async def end_voice_session(self, session_id: str) -> None:
        await self.storage.end_voice_session(session_id)

    async def append_voice_turn(self, session_id, learner_id, role, text) -> str:
        return await self.storage.append_voice_turn(session_id, learner_id, role, text)

    async def list_voice_sessions(self, learner_id: str, limit: int = 50) -> list[dict]:
        return await self.storage.list_voice_sessions(learner_id, limit)

    async def list_voice_turns(self, session_id: str) -> list[dict]:
        return await self.storage.list_voice_turns(session_id)

    # --- mem0-style aliases ---------------------------------------------
    # add -> ingest, search -> recall. Aliased to the same functions so a mem0
    # user is instantly productive; the canonical names carry the typed depth.
    add = ingest
    search = recall
