"""Guard against core/config.py's dataclass defaults drifting from
app/config.Settings' defaults — the factory (runtime/factory.py) maps one to
the other field-by-field, so a silent drift here would change behavior
without anyone noticing."""

import dataclasses

import pytest

from engram.app.config import Settings
from engram.core.config import KeeperConfig, RecallConfig

BASE_ENV = dict(
    openrouter_api_key="k", openai_api_key="k", database_url="d",
    model_tutor="m", model_extractor="m", model_reflector="m", model_embedder="m",
)


def _settings() -> Settings:
    return Settings(_env_file=None, **BASE_ENV)


def test_recall_config_defaults_match_settings_defaults():
    s = _settings()
    r = RecallConfig()
    assert r.w_recency == s.recall_w_recency
    assert r.w_importance == s.recall_w_importance
    assert r.w_relevance == s.recall_w_relevance
    assert r.seed_k == s.recall_seed_k
    assert r.hops == s.recall_hops
    assert r.fanout == s.recall_fanout
    assert r.default_budget == s.recall_default_budget
    assert r.session_buffer == s.recall_session_buffer
    assert r.history_turns == s.recall_history_turns


def test_keeper_config_defaults_match_settings_defaults():
    s = _settings()
    k = KeeperConfig()
    assert k.tau_high == s.keeper_tau_high
    assert k.tau_low == s.keeper_tau_low
    assert k.ewma_alpha == s.keeper_ewma_alpha
    assert k.salience_bump == s.keeper_salience_bump
    assert k.prune_floor == s.keeper_prune_floor
    # Critical cross-wiring: there is NO `keeper_decay` setting — the keeper's
    # decay comes from `recall_decay`. KeeperConfig.decay's default must match
    # Settings.recall_decay (not some independent "keeper decay" default).
    assert k.decay == s.recall_decay


def test_configs_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        RecallConfig().seed_k = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        KeeperConfig().tau_high = 0.1  # type: ignore[misc]


def test_recall_config_fields_match_settings_recall_knobs():
    """Set-equality drift guard: the field-by-field tests above only check
    that fields *present on both sides* have matching defaults — they don't
    fail if a field is added to only one side. This does: strip the
    `recall_` prefix off every Settings recall knob (excluding `recall_decay`,
    which cross-wires to KeeperConfig.decay, not RecallConfig) and assert the
    result is exactly RecallConfig's field-name set, both ways."""
    dataclass_fields = {f.name for f in dataclasses.fields(RecallConfig)}
    settings_recall_knobs = {
        name.removeprefix("recall_")
        for name in Settings.model_fields
        if name.startswith("recall_") and name != "recall_decay"
    }
    assert dataclass_fields == settings_recall_knobs


def test_keeper_config_fields_match_settings_keeper_knobs():
    """Same drift guard for KeeperConfig. `decay` is added back explicitly:
    it maps from `Settings.recall_decay`, not a `keeper_*` field (there is no
    `keeper_decay` setting — see the cross-wiring note in core/config.py)."""
    dataclass_fields = {f.name for f in dataclasses.fields(KeeperConfig)}
    settings_keeper_knobs = {
        name.removeprefix("keeper_")
        for name in Settings.model_fields
        if name.startswith("keeper_")
    }
    assert dataclass_fields == settings_keeper_knobs | {"decay"}
