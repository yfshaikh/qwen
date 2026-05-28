import pytest

from engram.app.config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example/v1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "tutor-x")
    monkeypatch.setenv("ENGRAM_MODEL_EXTRACTOR", "extractor-x")
    monkeypatch.setenv("ENGRAM_MODEL_REFLECTOR", "reflector-x")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "embedder-x")
    monkeypatch.setenv("ENGRAM_EMBEDDING_DIM", "1024")

    s = Settings()
    assert s.dashscope_api_key == "sk-test"
    assert s.dashscope_base_url == "https://example/v1"
    assert s.database_url == "postgresql://x"
    assert s.embedding_dim == 1024
    assert s.model_for("tutor") == "tutor-x"
    assert s.model_for("extractor") == "extractor-x"
    assert s.model_for("reflector") == "reflector-x"
    assert s.model_for("embedder") == "embedder-x"


def test_model_for_unknown_role(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "x")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "x")
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "t")
    monkeypatch.setenv("ENGRAM_MODEL_EXTRACTOR", "e")
    monkeypatch.setenv("ENGRAM_MODEL_REFLECTOR", "r")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "em")
    s = Settings()
    with pytest.raises(KeyError):
        s.model_for("nonsense")
