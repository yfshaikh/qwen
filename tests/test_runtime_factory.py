"""runtime.factory.from_env — the composition root moved out of core.

Guards the critical cross-wiring: KeeperConfig.decay comes from
ENGRAM_RECALL_DECAY (there is no ENGRAM_KEEPER_DECAY). A naive
`KeeperConfig()` default in the factory would silently drop this override —
exactly the regression this test exists to catch.
"""
from engram.core.config import KeeperConfig, RecallConfig
from engram.runtime.factory import configs_from_settings, from_env

BASE_ENV = dict(
    DASHSCOPE_API_KEY="sk-ds-test",
    DATABASE_URL="postgresql://engram:engram@localhost:5432/engram",
    ENGRAM_MODEL_TUTOR="m",
    ENGRAM_MODEL_EXTRACTOR="m",
    ENGRAM_MODEL_REFLECTOR="m",
    ENGRAM_MODEL_EMBEDDER="m",
)


def _set_env(monkeypatch, **overrides):
    for k, v in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(k, v)


def test_recall_decay_override_reaches_keeper_decay(monkeypatch):
    _set_env(monkeypatch, ENGRAM_RECALL_DECAY="0.9")
    eng = from_env(_env_file=None)
    try:
        assert eng._keeper.decay == 0.9  # KeeperConfig, not a hardcoded default
        keeper = eng._make_keeper()
        assert keeper.params.decay == 0.9  # the Keeper actually built from it
    finally:
        pass  # not connected — nothing to close


def test_recall_config_has_no_decay_field():
    assert not hasattr(RecallConfig(), "decay")


def test_configs_from_settings_maps_decay_to_keeper_not_recall(monkeypatch):
    from engram.app.config import Settings

    _set_env(monkeypatch, ENGRAM_RECALL_DECAY="0.42")
    settings = Settings(_env_file=None)
    recall, keeper = configs_from_settings(settings)
    assert isinstance(recall, RecallConfig)
    assert isinstance(keeper, KeeperConfig)
    assert keeper.decay == 0.42


def test_configs_from_settings_pins_every_field(monkeypatch):
    """Pin the entire hand-written field map in `configs_from_settings`.

    Every knob below is given a distinct, non-default value so a mis-map or
    permutation (e.g. w_recency <-> w_relevance, tau_high <-> tau_low) fails
    loudly by naming the field, instead of silently type-checking and passing
    the rest of the suite.
    """
    from engram.app.config import Settings

    _set_env(
        monkeypatch,
        ENGRAM_RECALL_W_RECENCY="0.11",
        ENGRAM_RECALL_W_IMPORTANCE="0.22",
        ENGRAM_RECALL_W_RELEVANCE="0.33",
        ENGRAM_RECALL_SEED_K="4",
        ENGRAM_RECALL_HOPS="5",
        ENGRAM_RECALL_FANOUT="6",
        ENGRAM_RECALL_DEFAULT_BUDGET="777",
        ENGRAM_RECALL_SESSION_BUFFER="false",
        ENGRAM_RECALL_HISTORY_TURNS="9",
        ENGRAM_RECALL_DECAY="0.91",
        ENGRAM_KEEPER_TAU_HIGH="0.71",
        ENGRAM_KEEPER_TAU_LOW="0.61",
        ENGRAM_KEEPER_EWMA_ALPHA="0.41",
        ENGRAM_KEEPER_SALIENCE_BUMP="0.31",
        ENGRAM_KEEPER_PRUNE_FLOOR="0.21",
    )
    settings = Settings(_env_file=None)
    recall, keeper = configs_from_settings(settings)

    assert recall.w_recency == 0.11
    assert recall.w_importance == 0.22
    assert recall.w_relevance == 0.33
    assert recall.seed_k == 4
    assert recall.hops == 5
    assert recall.fanout == 6
    assert recall.default_budget == 777
    assert recall.session_buffer is False
    assert recall.history_turns == 9

    assert keeper.tau_high == 0.71
    assert keeper.tau_low == 0.61
    assert keeper.ewma_alpha == 0.41
    assert keeper.salience_bump == 0.31
    assert keeper.prune_floor == 0.21
    # Cross-wiring: KeeperConfig.decay comes from settings.recall_decay, NOT
    # a (nonexistent) settings.keeper_decay — see configs_from_settings'
    # docstring. This must stay 0.91 (the recall_decay value above), not
    # keeper_tau_*/keeper_* values.
    assert keeper.decay == 0.91
