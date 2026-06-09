import pytest

from engram.app.config import Settings


def test_defaults_boot_without_env():
    s = Settings(_env_file=None)
    assert s.embedder_kind == "local"
    assert s.storage_backend == "postgres"
    assert s.embedding_dim == 1024
    assert s.openrouter_base_url.endswith("/api/v1")
    # Every role has a default model so the app composes without configuration.
    for role in ("tutor", "extractor", "reflector", "embedder"):
        assert s.model_for(role)


def test_env_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "tutor-x")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "embedder-x")
    monkeypatch.setenv("ENGRAM_EMBEDDER_KIND", "api")
    monkeypatch.setenv("ENGRAM_EMBEDDING_DIM", "512")
    monkeypatch.setenv("ENGRAM_STORAGE_BACKEND", "memory")

    s = Settings(_env_file=None)
    assert s.openrouter_api_key == "sk-test"
    assert s.model_for("tutor") == "tutor-x"
    assert s.model_for("embedder") == "embedder-x"
    assert s.embedder_kind == "api"
    assert s.embedding_dim == 512
    assert s.storage_backend == "memory"


def test_model_for_unknown_role():
    s = Settings(_env_file=None)
    with pytest.raises(KeyError):
        s.model_for("nonsense")
