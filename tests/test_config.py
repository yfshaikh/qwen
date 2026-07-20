import pytest

from engram.app.config import Settings

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-ds-test",
    "DATABASE_URL": "postgresql://engram:engram@localhost:5432/engram",
    "ENGRAM_MODEL_TUTOR": "qwen-max",
    "ENGRAM_MODEL_EXTRACTOR": "qwen-turbo",
    "ENGRAM_MODEL_REFLECTOR": "qwen-plus",
    "ENGRAM_MODEL_EMBEDDER": "text-embedding-v4",
}


def _settings(monkeypatch, **overrides):
    env = {**BASE_ENV, **overrides}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # _env_file=None ensures the test ignores any real .env on disk.
    return Settings(_env_file=None)


def test_loads_from_env(monkeypatch):
    s = _settings(monkeypatch)
    assert s.dashscope_api_key == "sk-ds-test"
    assert s.dashscope_base_url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert s.database_url.endswith("/engram")
    assert s.embedding_dim == 1024  # default


def test_model_for_resolves_roles(monkeypatch):
    s = _settings(monkeypatch)
    assert s.model_for("tutor") == "qwen-max"
    assert s.model_for("extractor") == "qwen-turbo"
    assert s.model_for("reflector") == "qwen-plus"
    assert s.model_for("embedder") == "text-embedding-v4"


def test_model_defaults_are_qwen(monkeypatch):
    for k in ("ENGRAM_MODEL_TUTOR", "ENGRAM_MODEL_EXTRACTOR",
              "ENGRAM_MODEL_REFLECTOR", "ENGRAM_MODEL_EMBEDDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    s = Settings(_env_file=None)
    assert s.model_for("tutor") == "qwen-plus"
    assert s.model_for("extractor") == "qwen-plus"
    assert s.model_for("reflector") == "qwen-plus"
    assert s.model_for("embedder") == "text-embedding-v3"


def test_model_for_unknown_role_raises(monkeypatch):
    s = _settings(monkeypatch)
    with pytest.raises(KeyError):
        s.model_for("nope")


def test_embedding_dim_override(monkeypatch):
    s = _settings(monkeypatch, ENGRAM_EMBEDDING_DIM="512")
    assert s.embedding_dim == 512


def test_recall_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.recall_w_recency == 0.3
    assert s.recall_w_importance == 0.3
    assert s.recall_w_relevance == 0.4
    assert s.recall_seed_k == 8
    assert s.recall_hops == 2
    assert s.recall_fanout == 10
    assert s.recall_default_budget == 800


def test_recall_overrides(monkeypatch):
    s = _settings(
        monkeypatch,
        ENGRAM_RECALL_W_RELEVANCE="0.6",
        ENGRAM_RECALL_SEED_K="3",
        ENGRAM_RECALL_DEFAULT_BUDGET="500",
    )
    assert s.recall_w_relevance == 0.6
    assert s.recall_seed_k == 3
    assert s.recall_default_budget == 500


def test_keeper_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.keeper_tau_high == 0.86
    assert s.keeper_tau_low == 0.72
    assert s.keeper_ewma_alpha == 0.3
    assert s.keeper_salience_bump == 0.3
    assert s.keeper_prune_floor == 0.05


def test_keeper_overrides(monkeypatch):
    s = _settings(monkeypatch, ENGRAM_KEEPER_TAU_HIGH="0.9", ENGRAM_KEEPER_PRUNE_FLOOR="0.1")
    assert s.keeper_tau_high == 0.9
    assert s.keeper_prune_floor == 0.1


def test_audit_settings(monkeypatch):
    s = _settings(monkeypatch)
    assert s.audit_poll_seconds == 1.0
    assert s.audit_page_limit == 100
    s2 = _settings(monkeypatch, ENGRAM_AUDIT_POLL_SECONDS="0.5", ENGRAM_AUDIT_PAGE_LIMIT="50")
    assert s2.audit_poll_seconds == 0.5
    assert s2.audit_page_limit == 50


def test_recall_session_buffer_default_on(monkeypatch):
    s = _settings(monkeypatch)
    assert s.recall_session_buffer is True


def test_recall_history_turns_default_and_override(monkeypatch):
    s = _settings(monkeypatch)
    assert s.recall_history_turns == 10
    s2 = _settings(monkeypatch, ENGRAM_RECALL_HISTORY_TURNS="4")
    assert s2.recall_history_turns == 4
