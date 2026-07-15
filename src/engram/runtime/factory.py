"""The composition root, moved out of `core` (WS-1a/1d): builds `Settings`,
concrete adapters, and the domain `RecallConfig`/`KeeperConfig` from env, then
wires them into an `Engram`. `core` has no outward imports at module level —
it is importable standalone, without adapters or `app.config` ever loading.
`Engram.from_env()` is a thin shim that lazily delegates to this module's
`from_env`, which is the one deliberate (lazy-broken) cycle: it only executes
inside the classmethod body, so it never fires at `core.engram` import time.
"""

from __future__ import annotations

from typing import Any

from engram.core.config import KeeperConfig, RecallConfig
from engram.core.engram import Engram


def configs_from_settings(settings: Any) -> tuple[RecallConfig, KeeperConfig]:
    """Map `Settings`' domain knobs onto the core dataclasses.

    Critical field map — preserve the current cross-wiring exactly:
    KeeperConfig.decay comes from settings.recall_decay (there is NO
    keeper_decay setting; Engram.consolidate()/repair_merges() build
    KeeperParams(decay=s.recall_decay, ...) today via `_make_keeper`).

    Shared by `from_env` and by eval tooling (tier-2 sweeps) that rebuilds an
    Engram against a modified Settings and needs the same mapping.
    """
    recall = RecallConfig(
        w_recency=settings.recall_w_recency,
        w_importance=settings.recall_w_importance,
        w_relevance=settings.recall_w_relevance,
        seed_k=settings.recall_seed_k,
        hops=settings.recall_hops,
        fanout=settings.recall_fanout,
        default_budget=settings.recall_default_budget,
        session_buffer=settings.recall_session_buffer,
        history_turns=settings.recall_history_turns,
    )
    keeper = KeeperConfig(
        tau_high=settings.keeper_tau_high,
        tau_low=settings.keeper_tau_low,
        ewma_alpha=settings.keeper_ewma_alpha,
        salience_bump=settings.keeper_salience_bump,
        prune_floor=settings.keeper_prune_floor,
        decay=settings.recall_decay,
    )
    return recall, keeper


def from_env(now: Any = None, **settings_kwargs: Any) -> Engram:
    """Build a fully-wired Engram from environment/.env via Settings.

    Pass `_env_file=None` to ignore any on-disk .env (used in tests).
    Call `await connect()` afterwards to open the storage pool.
    """
    from engram.adapters.llm.openai_compatible import build_llm
    from engram.adapters.llm.openai_embedder import build_embedder
    from engram.adapters.storage.postgres import PostgresStorage
    from engram.app.config import Settings

    settings = Settings(**settings_kwargs)
    recall, keeper = configs_from_settings(settings)

    return Engram(
        storage=PostgresStorage(settings.database_url),
        llm=build_llm(settings),
        embedder=build_embedder(settings),
        settings=settings,
        now=now,
        recall=recall,
        keeper=keeper,
    )
