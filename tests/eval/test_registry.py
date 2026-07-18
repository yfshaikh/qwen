import pytest

from engram.eval.registry import (
    CheckResult, EvalContext, all_checks, check, clear_registry, get_check, run_check,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_registry()
    yield
    clear_registry()


def _ctx(params=None):
    return EvalContext(eng=None, scenario=None, learner_id="x", snapshots=[],
                       transcript=[], clock=None, params=params or {})


async def test_register_get_and_run():
    @check("ok")
    async def ok(ctx):
        return CheckResult(name="ok", metrics={"m": 1.0}, passed=True)
    rc = get_check("ok")
    res = await run_check(rc, _ctx())
    assert res.passed and res.metrics == {"m": 1.0} and res.error is None
    assert "ok" in all_checks()


def test_duplicate_name_rejected():
    @check("dup")
    async def a(ctx): ...
    with pytest.raises(ValueError):
        @check("dup")
        async def b(ctx): ...


def test_unknown_name_lists_available():
    @check("known")
    async def k(ctx): ...
    with pytest.raises(KeyError) as e:
        get_check("nope")
    assert "known" in str(e.value)


async def test_crash_shield():
    @check("boom")
    async def boom(ctx):
        raise TypeError("bad")
    res = await run_check(get_check("boom"), _ctx())
    assert res.passed is False and "TypeError: bad" in res.error


async def test_threshold_and_param():
    ctx = _ctx({"threshold": 0.2, "foo": "bar"})
    assert ctx.threshold(0.05) == 0.2
    assert ctx.param("foo") == "bar"
    assert _ctx().threshold(0.05) == 0.05
