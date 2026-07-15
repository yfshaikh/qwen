"""Domain config for the memory core — plain frozen dataclasses, no pydantic,
no dependency on `app.config.Settings` or any adapter. `core` must be
constructible without the web layer; this module is where its tunable knobs
live so `Engram` never has to reach outward for them.

The composition root (`runtime/factory.py`) is what turns env-loaded
`Settings` into these dataclasses; `core` only ever sees the dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecallConfig:
    w_recency: float = 0.3
    w_importance: float = 0.3
    w_relevance: float = 0.4
    seed_k: int = 8
    hops: int = 2
    fanout: int = 10
    default_budget: int = 800
    session_buffer: bool = True
    history_turns: int = 10
    # NOTE: no `decay` here — recall has no decay param (Recall.__init__ takes
    # none). `recall_decay` is consumed ONLY by the keeper (see KeeperConfig).


@dataclass(frozen=True)
class KeeperConfig:
    tau_high: float = 0.86
    tau_low: float = 0.72
    ewma_alpha: float = 0.3
    salience_bump: float = 0.3
    prune_floor: float = 0.05
    decay: float = 0.98  # today == Settings.recall_decay (no keeper_decay setting)
