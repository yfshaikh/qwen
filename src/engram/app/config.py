"""env-loaded settings. The role->model map is the #1 cost lever (spec §2).

Chat (tutor/extractor/reflector) goes through OpenRouter; embeddings go through
OpenAI. Two providers, two keys, two base URLs.
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
        populate_by_name=True,
    )

    # Chat provider (OpenRouter)
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Embeddings provider (OpenAI)
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"

    # Database
    database_url: str

    # Role -> model
    model_tutor: str = Field(alias="ENGRAM_MODEL_TUTOR")
    model_extractor: str = Field(alias="ENGRAM_MODEL_EXTRACTOR")
    model_reflector: str = Field(alias="ENGRAM_MODEL_REFLECTOR")
    model_embedder: str = Field(alias="ENGRAM_MODEL_EMBEDDER")
    model_student: str | None = Field(default=None, alias="ENGRAM_MODEL_STUDENT")
    model_judge: str | None = Field(default=None, alias="ENGRAM_MODEL_JUDGE")

    embedding_dim: int = Field(default=1024, alias="ENGRAM_EMBEDDING_DIM")

    # Recall scoring + traversal (spec §4.4); env-overridable for eval sweeps.
    recall_w_recency: float = Field(default=0.3, alias="ENGRAM_RECALL_W_RECENCY")
    recall_w_importance: float = Field(default=0.3, alias="ENGRAM_RECALL_W_IMPORTANCE")
    recall_w_relevance: float = Field(default=0.4, alias="ENGRAM_RECALL_W_RELEVANCE")
    recall_decay: float = Field(default=0.98, alias="ENGRAM_RECALL_DECAY")  # Keeper (Phase 2)
    recall_seed_k: int = Field(default=8, alias="ENGRAM_RECALL_SEED_K")
    recall_hops: int = Field(default=2, alias="ENGRAM_RECALL_HOPS")
    recall_fanout: int = Field(default=10, alias="ENGRAM_RECALL_FANOUT")
    recall_default_budget: int = Field(default=800, alias="ENGRAM_RECALL_DEFAULT_BUDGET")
    recall_session_buffer: bool = Field(default=True, alias="ENGRAM_RECALL_SESSION_BUFFER")

    # Keeper / consolidation (spec §3.6); env-overridable for eval sweeps.
    keeper_tau_high: float = Field(default=0.86, alias="ENGRAM_KEEPER_TAU_HIGH")
    keeper_tau_low: float = Field(default=0.72, alias="ENGRAM_KEEPER_TAU_LOW")
    keeper_ewma_alpha: float = Field(default=0.3, alias="ENGRAM_KEEPER_EWMA_ALPHA")
    keeper_salience_bump: float = Field(default=0.3, alias="ENGRAM_KEEPER_SALIENCE_BUMP")
    keeper_prune_floor: float = Field(default=0.05, alias="ENGRAM_KEEPER_PRUNE_FLOOR")

    # Audit read / SSE tail (Phase 3a)
    audit_poll_seconds: float = Field(default=1.0, alias="ENGRAM_AUDIT_POLL_SECONDS")
    audit_page_limit: int = Field(default=100, alias="ENGRAM_AUDIT_PAGE_LIMIT")

    # Voice (Deepgram) — optional; None disables the voice route.
    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_stt_model: str = Field(default="nova-3", alias="DEEPGRAM_STT_MODEL")
    deepgram_tts_model: str = Field(default="aura-2-thalia-en", alias="DEEPGRAM_TTS_MODEL")
    deepgram_language: str | None = Field(default=None, alias="DEEPGRAM_LANGUAGE")

    # Eval harness (spec: eval-harness-v2)
    eval_ui: bool = Field(default=False, alias="ENGRAM_EVAL_UI")
    eval_price_in_per_m: float = Field(default=0.0, alias="ENGRAM_EVAL_PRICE_IN_PER_M")
    eval_price_out_per_m: float = Field(default=0.0, alias="ENGRAM_EVAL_PRICE_OUT_PER_M")

    def model_for(self, role: str) -> str:
        table = {
            "tutor": self.model_tutor,
            "extractor": self.model_extractor,
            "reflector": self.model_reflector,
            "embedder": self.model_embedder,
            "student": self.model_student or self.model_tutor,
            "judge": self.model_judge or self.model_reflector,
        }
        try:
            return table[role]
        except KeyError as e:
            raise KeyError(f"Unknown LLM role: {role!r}") from e
