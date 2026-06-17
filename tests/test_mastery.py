from engram.core.mastery import (
    decay_salience,
    ewma,
    observation_for,
    update_confidence,
)


def test_observation_kind_table():
    assert observation_for("quiz_correct") == 1.0
    assert observation_for("quiz_wrong") == 0.0
    assert observation_for("demonstrated") == 0.9
    assert observation_for("struggle") == 0.2
    assert observation_for("note") is None  # no mastery signal


def test_observation_signals_override():
    assert observation_for("struggle", correct=True) == 1.0
    assert observation_for("quiz_correct", correct=False) == 0.0
    assert observation_for("note", mastery=0.75) == 0.75


def test_ewma_first_obs_and_blend():
    assert ewma(None, 1.0, 0.3) == 1.0  # first observation
    assert ewma(0.0, 1.0, 0.3) == 0.3   # 0.3*1 + 0.7*0


def test_decay_salience():
    assert decay_salience(1.0, 0.0, 0.98) == 1.0
    assert round(decay_salience(1.0, 10.0, 0.98), 4) == round(0.98 ** 10, 4)
    assert decay_salience(None, 5.0, 0.98) == 0.98 ** 5  # None -> 1.0 base


def test_confidence_rises_on_agreement_drops_on_conflict():
    # first real signal on a fresh node (mastery None): small rise, no conflict
    conf, conflicted = update_confidence(0.3, None, 1.0)
    assert conf == 0.4 and conflicted is False
    # agreement (both high)
    conf, conflicted = update_confidence(0.5, 0.8, 0.9)
    assert conf == 0.6 and conflicted is False
    # conflict (low mastery, high obs)
    conf, conflicted = update_confidence(0.5, 0.2, 0.9)
    assert conf == 0.3 and conflicted is True
