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
