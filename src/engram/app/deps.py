"""Composition root: build the adapters from Settings and expose FastAPI
dependency providers. This is the ONLY place concrete adapters are wired; the
app and core never name them. Tests override the providers below.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from engram.adapters.host.text_tutor import TextTutor
from engram.adapters.llm.openrouter import build_openrouter_llm
from engram.app.config import Settings
from engram.core.service import EngramService


@lru_cache
def get_settings() -> Settings:
    return Settings()


def build_storage(settings: Settings) -> Any:
    """Pick the storage backend: postgres (default) or in-memory (demos/tests)."""
    if settings.storage_backend == "memory":
        from engram.adapters.storage.memory import InMemoryStorage

        return InMemoryStorage()
    from engram.adapters.storage.postgres import PostgresStorage

    return PostgresStorage(settings.database_url)


# Process-lifetime singletons. main.py manages connect/close via the lifespan;
# tests use FastAPI dependency_overrides instead of these.
_storage: Any = None
_service: EngramService | None = None
_tutor: TextTutor | None = None


async def init_singletons(settings: Settings | None = None) -> None:
    global _storage, _service, _tutor
    settings = settings or get_settings()
    _storage = build_storage(settings)
    await _storage.connect()
    llm = build_openrouter_llm(settings)
    _service = EngramService(_storage, llm, embed_dim=settings.embedding_dim)
    _tutor = TextTutor(_service)


async def shutdown_singletons() -> None:
    global _storage, _service, _tutor
    if _storage is not None:
        await _storage.close()
    _storage = _service = _tutor = None


def get_storage() -> Any:
    if _storage is None:
        raise RuntimeError("Storage not initialized; call init_singletons() first")
    return _storage


def get_service() -> EngramService:
    if _service is None:
        raise RuntimeError("Service not initialized; call init_singletons() first")
    return _service


def get_tutor() -> TextTutor:
    if _tutor is None:
        raise RuntimeError("Tutor not initialized; call init_singletons() first")
    return _tutor


def get_llm() -> Any:
    return get_service().llm
