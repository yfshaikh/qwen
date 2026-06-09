"""env-loaded settings.

The role->model map is the #1 cost lever (DESIGN §4.7). The LLM provider is
OpenRouter (an OpenAI-compatible gateway), chosen so any model — Qwen, GPT,
Claude, Llama — is a config edit, not a refactor. Embeddings default to a local,
deterministic embedder so the whole pipeline runs with no API key; flip
`ENGRAM_EMBEDDER_KIND=api` to use a hosted embeddings endpoint.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `protected_namespaces=()` lets us use `model_*` field names without
    # tripping pydantic v2's reserved-prefix warning.
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=(),
    )

    # --- LLM provider: OpenRouter (OpenAI-compatible). Key optional so the app
    # boots without one; live calls fail until a key is provided. ---
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    # Optional OpenRouter attribution headers.
    app_title: str = Field(default="Engram", alias="ENGRAM_APP_TITLE")
    app_referer: str = Field(default="https://github.com/yfshaikh/qwen", alias="ENGRAM_APP_REFERER")

    # --- Storage ---
    database_url: str = Field(
        default="postgresql://engram:engram@localhost:5432/engram", alias="DATABASE_URL"
    )
    storage_backend: str = Field(default="postgres", alias="ENGRAM_STORAGE_BACKEND")  # postgres|memory

    # --- Role -> model (OpenRouter slugs; swap freely) ---
    model_tutor: str = Field(default="openai/gpt-4o-mini", alias="ENGRAM_MODEL_TUTOR")
    model_extractor: str = Field(default="openai/gpt-4o-mini", alias="ENGRAM_MODEL_EXTRACTOR")
    model_reflector: str = Field(default="openai/gpt-4o", alias="ENGRAM_MODEL_REFLECTOR")
    model_embedder: str = Field(
        default="openai/text-embedding-3-small", alias="ENGRAM_MODEL_EMBEDDER"
    )

    # --- Embeddings ---
    embedder_kind: str = Field(default="local", alias="ENGRAM_EMBEDDER_KIND")  # local|api
    embedding_dim: int = Field(default=1024, alias="ENGRAM_EMBEDDING_DIM")
    embeddings_base_url: str = Field(default="", alias="ENGRAM_EMBEDDINGS_BASE_URL")
    embeddings_api_key: str = Field(default="", alias="ENGRAM_EMBEDDINGS_API_KEY")

    # --- Keeper cron sweep (optional background loop) ---
    sweep_enabled: bool = Field(default=False, alias="ENGRAM_SWEEP_ENABLED")
    sweep_interval_seconds: int = Field(default=300, alias="ENGRAM_SWEEP_INTERVAL_SECONDS")
    sweep_quiet_seconds: int = Field(default=120, alias="ENGRAM_SWEEP_QUIET_SECONDS")

    def model_for(self, role: str) -> str:
        try:
            return {
                "tutor": self.model_tutor,
                "extractor": self.model_extractor,
                "reflector": self.model_reflector,
                "embedder": self.model_embedder,
            }[role]
        except KeyError as e:
            raise KeyError(f"Unknown LLM role: {role!r}") from e
