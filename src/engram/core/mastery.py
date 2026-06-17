"""Pure mastery math for the Keeper: observation mapping, EWMA, confidence, decay."""

from __future__ import annotations

# Evidence kind -> mastery observation (0..1). Kinds absent here carry no signal.
KIND_OBSERVATION: dict[str, float] = {
    "quiz_correct": 1.0,
    "demonstrated": 0.9,
    "quiz_wrong": 0.0,
    "struggle": 0.2,
}


def observation_for(
    kind: str, correct: bool | None = None, mastery: float | None = None
) -> float | None:
    """Mastery observation for one piece of evidence; signals override the table."""
    if mastery is not None:
        return max(0.0, min(1.0, mastery))
    if correct is not None:
        return 1.0 if correct else 0.0
    return KIND_OBSERVATION.get(kind)


def ewma(old: float | None, obs: float, alpha: float) -> float:
    """EWMA update; the first observation seeds the value directly."""
    if old is None:
        return obs
    return alpha * obs + (1 - alpha) * old


def update_confidence(
    old: float | None, old_mastery: float | None, obs: float
) -> tuple[float, bool]:
    """Return (new_confidence, conflicted). Rises on agreement, drops on conflict."""
    conf = 0.3 if old is None else old
    if old_mastery is None:  # first real signal — no prior to conflict with
        return (min(1.0, conf + 0.1), False)
    agree = (obs >= 0.5) == (old_mastery >= 0.5)
    if agree:
        return (min(1.0, conf + 0.1), False)
    return (max(0.0, conf - 0.2), True)


def decay_salience(salience: float | None, days: float, decay: float) -> float:
    """salience *= decay**days; a missing salience is treated as fully active (1.0)."""
    base = 1.0 if salience is None else salience
    return base * (decay ** days)
