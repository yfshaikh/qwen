"""CLI for the Engram ablation harness.

Usage::

    python -m eval.run [path/to/scenario.yaml]
    python -m eval                       # same, with the bundled scenario

Prints per-probe decisions, the metrics for both arms, and a HEADLINE line.
Exits 0 when the memory arm beats the baseline, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eval.harness import DEFAULT_SCENARIO, EvalResults, run_eval


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def format_report(results: EvalResults) -> str:
    lines: list[str] = []
    lines.append(
        f"Scenario: {results.scenario}  (learner={results.learner_id}, "
        f"mastery_threshold={results.mastery_threshold}, "
        f"baseline_window={results.baseline_window})"
    )
    lines.append("")

    # Per-probe decision table.
    header = (
        f"{'concept':<24} {'mastered':<9} {'memory':<12} {'baseline':<12} "
        f"{'memory hit':<11} {'baseline hit':<12}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for d in results.probes:
        mem = "re-explain" if d.memory_reexplained else "SKIP"
        base = "re-explain" if d.baseline_reexplained else "SKIP"
        lines.append(
            f"{d.concept:<24} {('yes' if d.mastered else 'no'):<9} {mem:<12} {base:<12} "
            f"{('yes' if d.memory_hit else 'no'):<11} {('yes' if d.baseline_hit else 'no'):<12}"
        )
    lines.append("")

    # Metrics table.
    lines.append(f"{'arm':<10} {'reexplain_rate_of_mastered':<28} {'prior_session_recall_hits'}")
    for arm in (results.memory, results.baseline):
        lines.append(
            f"{arm.arm:<10} {_pct(arm.reexplain_rate_of_mastered):<28} "
            f"{arm.prior_session_recall_hits}/{results.total_probes}"
        )
    lines.append("")

    mem_rate = results.memory.reexplain_rate_of_mastered
    base_rate = results.baseline.reexplain_rate_of_mastered
    reduction = _pct((base_rate - mem_rate) / base_rate) if base_rate > 0 else "n/a"
    lines.append(
        f"HEADLINE: With memory, the tutor re-explained mastered material {reduction} less "
        f"({_pct(mem_rate)} vs {_pct(base_rate)}) and recalled prior-session context "
        f"{results.memory.prior_session_recall_hits}/{results.total_probes} times vs "
        f"{results.baseline.prior_session_recall_hits}/{results.total_probes} for the "
        f"last-{results.baseline_window}-events baseline."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    scenario = Path(args[0]) if args else DEFAULT_SCENARIO

    results = asyncio.run(run_eval(scenario))
    print(format_report(results))

    memory_wins = (
        results.memory.reexplain_rate_of_mastered
        < results.baseline.reexplain_rate_of_mastered
        and results.memory.prior_session_recall_hits
        >= results.baseline.prior_session_recall_hits
    )
    return 0 if memory_wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
