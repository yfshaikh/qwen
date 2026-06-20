"""Composition root: a lifespan-managed Engram singleton + a dependency provider.
The ONLY place concrete wiring happens. Tests override get_engram with a fake."""

from __future__ import annotations

from engram.core.engram import Engram

_engram: Engram | None = None


async def init_engram() -> None:
    global _engram
    _engram = Engram.from_env()
    await _engram.connect()


async def shutdown_engram() -> None:
    global _engram
    if _engram is not None:
        await _engram.aclose()
        _engram = None


def get_engram() -> Engram:
    if _engram is None:
        raise RuntimeError("Engram not initialized; lifespan did not run")
    return _engram
