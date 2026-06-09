"""Tests for the Engram ablation harness (eval/).

Deterministic + offline: the harness drives a scripted FakeLLM + HashingEmbedder,
so these assert the demonstration holds -- memory re-explains mastered material
less than the baseline, and recalls prior-session context at least as often.

pytest is asyncio_mode=auto, so ``async def test_*`` needs no decorator.
"""

from __future__ import annotations

from pathlib import Path

from eval.harness import (
    DEFAULT_SCENARIO,
    baseline_should_reexplain,
    load_scenario,
    memory_should_reexplain,
    run_eval,
)
from eval.run import format_report, main
from engram.core.models import LearningEvent

SCENARIO = DEFAULT_SCENARIO


async def test_harness_runs_on_bundled_scenario():
    result = await run_eval()
    assert result.learner_id == "alice"
    assert result.probes  # non-empty
    # Both arms produced a decision for every probe.
    for probe in result.probes:
        c = probe["concept"]
        assert c in result.memory.reexplain
        assert c in result.baseline.reexplain


async def test_memory_reexplains_mastered_material_less_than_baseline():
    """The money-shot: memory's re-explain rate of mastered concepts is lower."""
    result = await run_eval()
    assert (
        result.memory.reexplain_rate_of_mastered
        < result.baseline.reexplain_rate_of_mastered
    )
    # In the bundled arc, memory re-explains NO mastered concept and the baseline
    # re-explains them all (their mastery evidence aged out of the last-N window).
    assert result.memory.reexplain_rate_of_mastered == 0.0
    assert result.baseline.reexplain_rate_of_mastered == 1.0


async def test_memory_recall_hits_at_least_baseline():
    result = await run_eval()
    assert (
        result.memory.prior_session_recall_hits
        >= result.baseline.prior_session_recall_hits
    )
    # Memory surfaces every probed concept; the baseline misses the oldest one.
    assert result.memory.prior_session_recall_hits == len(result.probes)
    assert result.baseline.prior_session_recall_hits < len(result.probes)


async def test_mastered_concept_is_skipped_by_memory_but_reexplained_by_baseline():
    """Per-concept: the mastered concept (derivatives) is the load-bearing case."""
    result = await run_eval()
    for concept in result.mastered_concepts:
        assert result.memory.reexplain[concept] is False, concept
        assert result.baseline.reexplain[concept] is True, concept
        # And memory believed it was mastered (>= threshold).
        m = result.memory.mastery[concept]
        assert m is not None and m >= result.mastery_threshold


async def test_determinism_repeated_runs_match():
    a = (await run_eval()).as_dict()
    b = (await run_eval()).as_dict()
    assert a == b


async def test_load_scenario_defaults_and_path():
    via_default = load_scenario()
    via_path = load_scenario(SCENARIO)
    assert via_default == via_path
    assert via_default["learner_id"] == "alice"
    assert via_default["mastery_threshold"] == 0.6
    assert isinstance(via_default["sessions"], list) and via_default["sessions"]


async def test_memory_policy_unit():
    """The memory policy keys off the recall subgraph's synthesized mastery."""
    sub = {"nodes": [{"label": "derivatives", "mastery": 0.8}]}
    reexplain, mastery, surfaced = memory_should_reexplain("derivatives", sub, 0.6)
    assert reexplain is False and mastery == 0.8 and surfaced is True

    # Below threshold -> re-explain, but still surfaced.
    sub_low = {"nodes": [{"label": "limits", "mastery": 0.4}]}
    reexplain, mastery, surfaced = memory_should_reexplain("limits", sub_low, 0.6)
    assert reexplain is True and mastery == 0.4 and surfaced is True

    # Absent -> re-explain, not surfaced.
    reexplain, mastery, surfaced = memory_should_reexplain("integrals", sub, 0.6)
    assert reexplain is True and mastery is None and surfaced is False


async def test_baseline_policy_unit():
    """The baseline policy keys off mastery evidence present in the window."""
    learner = "alice"
    # A window that still holds derivatives mastery evidence -> skip.
    have = [
        LearningEvent(
            learner_id=learner,
            type="quiz_result",
            text="differentiated x^2",
            signals={"mastery": 0.9, "concept": "derivatives"},
        )
    ]
    reexplain, mastery, surfaced = baseline_should_reexplain("derivatives", have, 0.6)
    assert reexplain is False and mastery == 0.9 and surfaced is True

    # A window that mentions the concept but with no mastery evidence -> re-explain.
    weak = [
        LearningEvent(learner_id=learner, type="utterance", text="derivatives are hard")
    ]
    reexplain, mastery, surfaced = baseline_should_reexplain("derivatives", weak, 0.6)
    assert reexplain is True and mastery is None and surfaced is True

    # A window that never mentions the concept -> re-explain, not surfaced.
    none = [LearningEvent(learner_id=learner, type="utterance", text="hi")]
    reexplain, mastery, surfaced = baseline_should_reexplain("derivatives", none, 0.6)
    assert reexplain is True and mastery is None and surfaced is False


async def test_format_report_mentions_headline_and_concepts():
    result = await run_eval()
    report = format_report(result)
    assert "HEADLINE" in report
    assert "derivatives" in report
    assert "memory" in report and "baseline" in report


def test_cli_main_returns_zero_when_demo_holds():
    # Plain (non-async) test: main() calls asyncio.run() internally, so it must
    # NOT run inside pytest-asyncio's event loop. The demo holds, so it exits 0.
    assert main([str(SCENARIO)]) == 0
    # No-arg path uses the bundled default.
    assert main([]) == 0


async def test_default_scenario_file_exists():
    assert Path(SCENARIO).is_file()
