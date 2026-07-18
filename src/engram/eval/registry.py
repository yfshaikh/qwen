"""Pluggable check registry. A check = one decorated async fn taking EvalContext.
Adding an eval for a new feature = one check file + one scenario YAML line."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class CheckResult:
    name: str
    metrics: dict[str, float]
    passed: bool
    details: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "metrics": self.metrics, "passed": self.passed,
                "details": self.details, "error": self.error}


@dataclass
class EvalContext:
    eng: Any
    scenario: Any
    learner_id: str
    snapshots: list[dict]
    transcript: list[dict]
    clock: Any
    params: dict

    def param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def threshold(self, default: float) -> float:
        return float(self.params.get("threshold", default))


CheckFn = Callable[[EvalContext], Awaitable[CheckResult]]


@dataclass(slots=True)
class RegisteredCheck:
    name: str
    needs: str  # "graph" (snapshots suffice) | "live" (spends LLM calls)
    fn: CheckFn


_REGISTRY: dict[str, RegisteredCheck] = {}


def check(name: str, needs: str = "graph"):
    def deco(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise ValueError(f"duplicate check name: {name!r}")
        _REGISTRY[name] = RegisteredCheck(name=name, needs=needs, fn=fn)
        return fn
    return deco


def get_check(name: str) -> RegisteredCheck:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown check {name!r}; available: {sorted(_REGISTRY)}") from None


def all_checks() -> dict[str, RegisteredCheck]:
    return dict(_REGISTRY)


def clear_registry() -> None:  # tests only
    _REGISTRY.clear()


async def run_check(rc: RegisteredCheck, ctx: EvalContext) -> CheckResult:
    try:
        res = await rc.fn(ctx)
        if not isinstance(res, CheckResult):
            return CheckResult(name=rc.name, metrics={}, passed=False,
                               error=f"check returned {type(res).__name__}, not CheckResult")
        return res
    except Exception as exc:  # noqa: BLE001 — a check must never kill the run
        return CheckResult(name=rc.name, metrics={}, passed=False,
                           error=f"{type(exc).__name__}: {exc}")
