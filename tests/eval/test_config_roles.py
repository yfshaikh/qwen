from engram.app.config import Settings

def _settings(**over):
    base = dict(
        _env_file=None,
        openrouter_api_key="k", openai_api_key="k", database_url="postgresql://x",
        model_tutor="t", model_extractor="x", model_reflector="r", model_embedder="e",
    )
    base.update(over)
    return Settings(**base)

def test_student_falls_back_to_tutor_when_unset():
    assert _settings().model_for("student") == "t"

def test_judge_falls_back_to_reflector_when_unset():
    assert _settings().model_for("judge") == "r"

def test_explicit_student_judge_win():
    s = _settings(model_student="s", model_judge="j")
    assert s.model_for("student") == "s"
    assert s.model_for("judge") == "j"


# --- temperature_for --------------------------------------------------------

def test_temperature_defaults_to_none_for_every_role():
    """None => omit `temperature` and take the provider default. Nothing changes
    unless a temperature is explicitly configured."""
    s = _settings()
    assert all(s.temperature_for(r) is None
               for r in ("tutor", "extractor", "reflector", "student", "judge"))

def test_temperature_is_per_role():
    """The seam that lets the frozen benchmark pin the extractor to 0 while leaving
    the production tutor alone — docs/eval-harness.md #1 deferred pinning
    temperature precisely because it assumed that wasn't possible."""
    s = _settings(temperature_extractor=0.0)
    assert s.temperature_for("extractor") == 0.0
    assert s.temperature_for("tutor") is None

def test_temperature_zero_is_not_confused_with_unset():
    """0.0 is falsy; a `or`-style default would silently drop the pin and make a
    'reproducible' run reproducible in name only."""
    s = _settings(temperature_extractor=0.0)
    assert s.temperature_for("extractor") is not None

def test_temperature_does_not_fall_back_like_model_for():
    """model_for maps student->tutor and judge->reflector. Temperature deliberately
    does not: inheriting a sampling choice across call sites would be surprising."""
    s = _settings(temperature_tutor=0.7, temperature_reflector=0.1)
    assert s.temperature_for("student") is None
    assert s.temperature_for("judge") is None

def test_temperature_unknown_role_returns_none_not_raises():
    """Unlike model_for, which raises. An embedder has no temperature, and callers
    pass whatever role they hold."""
    assert _settings().temperature_for("embedder") is None
    assert _settings().temperature_for("nonsense") is None
