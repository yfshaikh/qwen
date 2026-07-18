"""Aggregation gate: majority-of-N verdicts over runs, offline.

The pure half (aggregate/gate) is exercised with canned run dicts; the
orchestration half (execute_many) runs fully offline on the fakes, mirroring
test_runner's harness.
"""
import importlib

import pytest

import engram.eval.checks  # noqa: F401  (registration)
from engram.core.engram import Engram
from engram.eval.aggregate import CheckAgg, aggregate, gate, render, scored
from engram.eval.checks import integrity
from engram.eval.clock import SimClock
from engram.eval.registry import clear_registry
from engram.eval.runner import execute_many
from engram.eval.scenario import CheckSpec, Probe, Scenario, Session
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture(autouse=True)
def _register_checks():
    clear_registry()
    importlib.reload(integrity)


def _run(status="failed", **checks):
    return {"run_id": "r", "status": status, "cost": {"usd": 0.0},
            "checks": [{"name": k, "passed": v} for k, v in checks.items()]}


# --- pure aggregation -------------------------------------------------------

def test_aggregate_counts_and_flaky():
    runs = [_run(a=True, b=False), _run(a=True, b=True), _run(a=True, b=False)]
    by = aggregate(runs)
    assert by["a"].passes == 3 and not by["a"].flaky
    assert by["b"].passes == 1 and by["b"].flaky


def test_scored_excludes_crashed_and_empty():
    runs = [_run(a=True),
            {"run_id": "x", "status": "crashed", "checks": [], "cost": {"usd": 0}},
            {"run_id": "y", "status": "error", "checks": [], "cost": {"usd": 0}}]
    assert len(scored(runs)) == 1
    assert aggregate(runs)["a"].n == 1


def test_gate_requires_strict_majority_of_asked():
    # 2 passes of 3 asked -> gate passes even though one run flipped
    assert gate(aggregate([_run(a=True), _run(a=True), _run(a=False)]), 3)
    # 2 passes of 4 asked (exactly half) -> not a strict majority
    assert not gate(aggregate([_run(a=True), _run(a=True),
                               _run(a=False), _run(a=False)]), 4)
    # lost runs count against: 2 passes scored, but 5 were asked
    assert not gate(aggregate([_run(a=True), _run(a=True)]), 5)
    # no verdicts at all is a fail, not a vacuous pass
    assert not gate({}, 3)


def test_gate_fails_when_any_check_fails_majority():
    runs = [_run(a=True, b=False), _run(a=True, b=False), _run(a=True, b=True)]
    assert not gate(aggregate(runs), 3)


def test_render_flags_flaky():
    by = {"a": CheckAgg(name="a", passes=2, n=3)}
    out = render(by, n_asked=3, n_scored=3)
    assert "FLAKY" in out and "[PASS] a  2/3" in out


# --- offline orchestration --------------------------------------------------

EXTRACTION = (
    '{"concepts": [{"label": "Limits", "summary": "s",'
    ' "evidence": [{"kind": "asked_about", "content": "q"}]}],'
    ' "preferences": [], "goals": [], "relations": []}'
)


def _eng():
    return Engram(storage=FakeStorage(), llm=FakeLLM(canned_text=EXTRACTION),
                  embedder=FakeEmbedder(dim=64))


def _scenario():
    return Scenario(
        id="t", persona="p", hidden_state={},
        sessions=[Session(intent="ask", turns=1)],
        probes=[Probe(query="limits", expect_nodes=["Limits"])],
        checks=[CheckSpec(name="integrity")])


async def test_execute_many_offline(tmp_path):
    dirs = iter([tmp_path / f"r{i}" for i in range(3)])
    done: list[str] = []
    results = await execute_many(
        _eng(), _scenario(), lambda: next(dirs), n=3, concurrency=2,
        clock_factory=SimClock, on_done=lambda r: done.append(r["run_id"]))
    assert len(results) == 3 and len(done) == 3
    assert all(r["status"] == "passed" for r in results)
    assert gate(aggregate(results), 3)


async def test_execute_many_survives_a_crashed_run(tmp_path):
    calls = {"n": 0}

    def new_dir():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return tmp_path / f"r{calls['n']}"

    results = await execute_many(
        _eng(), _scenario(), new_dir, n=3, concurrency=1,
        clock_factory=SimClock)
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["crashed", "passed", "passed"]
    # 2 of 3 asked still a strict majority -> gate holds despite the crash
    assert gate(aggregate(results), 3)
    # but 2 of 5 would not
    assert not gate(aggregate(results), 5)
