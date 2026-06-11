"""Composition root: build adapters from Settings and expose FastAPI dependency
providers. The app module is the ONLY place that wires concrete adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from engram.adapters.llm.dashscope import DashScopeLLM, build_dashscope_llm
from engram.adapters.storage.postgres import PostgresStorage
from engram.app.config import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Singletons for the process lifetime. main.py manages connect/close on
# startup/shutdown. Tests override via FastAPI's dependency_overrides.
_storage: PostgresStorage | None = None
_llm: DashScopeLLM | None = None


async def init_singletons(settings: Settings | None = None) -> None:
    global _storage, _llm
    settings = settings or get_settings()
    _storage = PostgresStorage(settings.database_url)
    await _storage.connect()
    _llm = build_dashscope_llm(settings)


async def shutdown_singletons() -> None:
    global _storage, _llm
    if _storage is not None:
        await _storage.close()
    _storage = None
    _llm = None


def get_storage() -> Any:
    if _storage is None:
        raise RuntimeError("Storage not initialized; call init_singletons() first")
    return _storage


def get_llm() -> Any:
    if _llm is None:
        raise RuntimeError("LLM not initialized; call init_singletons() first")
    return _llm
