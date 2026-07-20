"""env-loaded settings. The role->model map is the #1 cost lever (spec §2).

Everything runs on Alibaba Cloud Model Studio (DashScope): chat, embeddings,
and ASR share the OpenAI-compatible endpoint; TTS uses the DashScope-native
REST endpoint (see voice/tts.py). One provider, one key.
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

    # Alibaba Cloud Model Studio (DashScope). One key for chat + embeddings +
    # ASR (OpenAI-compatible endpoint) and TTS (DashScope-native endpoint).
    # The intl (Singapore) base URL is the hackathon-recognized one.
    dashscope_api_key: str
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # Database
    database_url: str

    # Role -> model (Qwen defaults; env-overridable per role)
    model_tutor: str = Field(default="qwen-plus", alias="ENGRAM_MODEL_TUTOR")
    model_extractor: str = Field(default="qwen-plus", alias="ENGRAM_MODEL_EXTRACTOR")
    model_reflector: str = Field(default="qwen-plus", alias="ENGRAM_MODEL_REFLECTOR")
    model_embedder: str = Field(default="text-embedding-v3", alias="ENGRAM_MODEL_EMBEDDER")
    model_student: str | None = Field(default=None, alias="ENGRAM_MODEL_STUDENT")
    model_judge: str | None = Field(default=None, alias="ENGRAM_MODEL_JUDGE")

    # Role -> sampling temperature. None = provider default (today's behavior;
    # nothing changes unless you set one).
    #
    # Why per-role: a frozen-transcript eval (eval/scenarios/em-frozen-v1.yaml)
    # pins the input, which makes SAMPLING the only remaining source of variance.
    # Extractor+reflector at 0 is what turns that fixture into a gate. The tutor
    # is deliberately left alone — docs/eval-harness.md #1 deferred pinning
    # temperature because it "would also change the production tutor"; per-role
    # is exactly the seam that makes the deferral unnecessary.
    #
    # Caveat: temperature=0 is not bit-deterministic on most providers (request
    # batching, float non-associativity). Close enough to gate on; not close
    # enough to assume.
    temperature_tutor: float | None = Field(default=None, alias="ENGRAM_TEMPERATURE_TUTOR")
    temperature_extractor: float | None = Field(default=None, alias="ENGRAM_TEMPERATURE_EXTRACTOR")
    temperature_reflector: float | None = Field(default=None, alias="ENGRAM_TEMPERATURE_REFLECTOR")
    temperature_student: float | None = Field(default=None, alias="ENGRAM_TEMPERATURE_STUDENT")
    temperature_judge: float | None = Field(default=None, alias="ENGRAM_TEMPERATURE_JUDGE")

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
    recall_history_turns: int = Field(default=10, alias="ENGRAM_RECALL_HISTORY_TURNS")

    # Keeper / consolidation (spec §3.6); env-overridable for eval sweeps.
    keeper_tau_high: float = Field(default=0.86, alias="ENGRAM_KEEPER_TAU_HIGH")
    keeper_tau_low: float = Field(default=0.72, alias="ENGRAM_KEEPER_TAU_LOW")
    keeper_ewma_alpha: float = Field(default=0.3, alias="ENGRAM_KEEPER_EWMA_ALPHA")
    keeper_salience_bump: float = Field(default=0.3, alias="ENGRAM_KEEPER_SALIENCE_BUMP")
    keeper_prune_floor: float = Field(default=0.05, alias="ENGRAM_KEEPER_PRUNE_FLOOR")

    # Audit read / SSE tail (Phase 3a)
    audit_poll_seconds: float = Field(default=1.0, alias="ENGRAM_AUDIT_POLL_SECONDS")
    audit_page_limit: int = Field(default=100, alias="ENGRAM_AUDIT_PAGE_LIMIT")

    # Voice (DashScope) — same key as chat. ASR rides the OpenAI-compatible
    # endpoint; TTS hits the multimodal-generation REST endpoint.
    stt_model: str = Field(default="qwen3-asr-flash", alias="ENGRAM_STT_MODEL")
    stt_language: str | None = Field(default=None, alias="ENGRAM_STT_LANGUAGE")
    tts_model: str = Field(default="qwen3-tts-flash", alias="ENGRAM_TTS_MODEL")
    tts_voice: str = Field(default="Cherry", alias="ENGRAM_TTS_VOICE")

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

    def temperature_for(self, role: str) -> float | None:
        """Sampling temperature for a role, or None to use the provider default.

        Deliberately does NOT fall back the way model_for does (student->tutor,
        judge->reflector): a temperature is a sampling choice per call site, and
        silently inheriting the tutor's would be surprising. Unknown roles (e.g.
        "embedder") return None rather than raising — an embedder has no
        temperature, and callers pass whatever role they hold.
        """
        return {
            "tutor": self.temperature_tutor,
            "extractor": self.temperature_extractor,
            "reflector": self.temperature_reflector,
            "student": self.temperature_student,
            "judge": self.temperature_judge,
        }.get(role)
