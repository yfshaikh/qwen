import pytest

from engram.app.config import Settings

BASE_ENV = {
    "OPENROUTER_API_KEY": "sk-or-test",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENAI_API_KEY": "sk-test",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "DATABASE_URL": "postgresql://engram:engram@localhost:5432/engram",
    "ENGRAM_MODEL_TUTOR": "qwen/qwen3-vl-235b-a22b-instruct",
    "ENGRAM_MODEL_EXTRACTOR": "qwen/qwen-turbo",
    "ENGRAM_MODEL_REFLECTOR": "qwen/qwen-max",
    "ENGRAM_MODEL_EMBEDDER": "text-embedding-3-small",
}


def _settings(monkeypatch, **overrides):
    env = {**BASE_ENV, **overrides}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # _env_file=None ensures the test ignores any real .env on disk.
    return Settings(_env_file=None)


def test_loads_from_env(monkeypatch):
    s = _settings(monkeypatch)
    assert s.openrouter_api_key == "sk-or-test"
    assert s.database_url.endswith("/engram")
    assert s.embedding_dim == 1024  # default


def test_model_for_resolves_roles(monkeypatch):
    s = _settings(monkeypatch)
    assert s.model_for("tutor") == "qwen/qwen3-vl-235b-a22b-instruct"
    assert s.model_for("extractor") == "qwen/qwen-turbo"
    assert s.model_for("reflector") == "qwen/qwen-max"
    assert s.model_for("embedder") == "text-embedding-3-small"


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
