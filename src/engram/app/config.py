"""env-loaded settings. The role->model map is the #1 cost lever (spec §2)."""

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

    # Required
    dashscope_api_key: str
    dashscope_base_url: str
    database_url: str

    # Role -> model
    model_tutor: str = Field(alias="ENGRAM_MODEL_TUTOR")
    model_extractor: str = Field(alias="ENGRAM_MODEL_EXTRACTOR")
    model_reflector: str = Field(alias="ENGRAM_MODEL_REFLECTOR")
    model_embedder: str = Field(alias="ENGRAM_MODEL_EMBEDDER")

    embedding_dim: int = Field(default=1024, alias="ENGRAM_EMBEDDING_DIM")

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
