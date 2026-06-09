"""Eval/ablation harness tests — memory arm vs last-N-events baseline.

All offline + deterministic: scripted FakeLLM extractions, HashingEmbedder
vectors, InMemoryStorage. The bundled scenario masters two concepts in session
1, then pushes them out of the baseline's last-10-events window by session 3.
"""

from __future__ import annotations

from eval.harness import DEFAULT_SCENARIO, baseline_should_reexplain, load_scenario, run_eval
from eval.run import main


async def test_harness_runs_bundled_scenario():
    results = await run_eval(DEFAULT_SCENARIO)

    assert results.scenario == "derivatives-arc"
    assert results.total_probes == 3
    assert results.mastered_probes == 2
    assert len(results.probes) == results.total_probes
    # The non-mastered probe should be re-explained by BOTH arms (sanity: the
    # memory policy is not trivially "never re-explain").
    fresh = next(p for p in results.probes if not p.mastered)
    assert fresh.memory_reexplained and fresh.baseline_reexplained


async def test_memory_reexplains_mastered_material_less_than_baseline():
    results = await run_eval(DEFAULT_SCENARIO)

    assert (
        results.memory.reexplain_rate_of_mastered
        < results.baseline.reexplain_rate_of_mastered
    )
    # Money shot for the bundled scenario: 0% vs 100%.
    assert results.memory.reexplain_rate_of_mastered == 0.0
    assert results.baseline.reexplain_rate_of_mastered == 1.0


async def test_memory_recall_hits_at_least_baseline():
    results = await run_eval(DEFAULT_SCENARIO)

    assert results.memory.prior_session_recall_hits >= results.baseline.prior_session_recall_hits
    # Memory surfaces every probed concept; the baseline window lost session 1.
    assert results.memory.prior_session_recall_hits == results.total_probes
    assert results.baseline.prior_session_recall_hits < results.total_probes


async def test_baseline_fails_only_because_of_the_window():
    """With an unbounded window the baseline WOULD see the mastery evidence —
    the ablation isolates the limited-context problem, not a strawman policy."""
    scenario = load_scenario(DEFAULT_SCENARIO)
    threshold = scenario["mastery_threshold"]

    from eval.harness import _event  # mechanical helper; fine for tests

    all_events = [
        _event(scenario["learner_id"], raw)
        for session in scenario["sessions"]
        for raw in session["events"]
    ]
    assert baseline_should_reexplain(all_events, "chain rule", threshold) is False
    window = all_events[-scenario["baseline_window"] :]
    assert baseline_should_reexplain(window, "chain rule", threshold) is True


async def test_determinism_across_runs():
    first = await run_eval(DEFAULT_SCENARIO)
    second = await run_eval(DEFAULT_SCENARIO)
    assert first == second


def test_cli_main_prints_report_and_exits_zero(capsys):
    # main() calls asyncio.run, so this test must stay a plain sync def.
    exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "HEADLINE:" in out
    assert "memory" in out and "baseline" in out
