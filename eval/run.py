"""CLI for the Engram ablation harness.

Usage::

    cd /home/user/qwen && .venv/bin/python -m eval.run [scenario.yaml]

Runs the bundled (or a given) scenario through both arms and prints a clear
before/after table plus the headline number. Fully deterministic and offline.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eval.harness import EvalResult, run_eval


def _yn(reexplain: bool) -> str:
    return "RE-EXPLAIN" if reexplain else "skip"


def _mastery(value: float | None) -> str:
    return "  --  " if value is None else f"{value:.2f}"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _probe_table(result: EvalResult) -> str:
    """Per-probe decision table for both arms."""
    rows = [
        "  concept       mastered   memory(mastery -> action)      baseline(mastery -> action)",
        "  " + "-" * 84,
    ]
    mastered = set(result.mastered_concepts)
    for probe in result.probes:
        c = probe["concept"]
        is_m = "yes" if c in mastered else "no"
        m_act = f"{_mastery(result.memory.mastery.get(c))} -> {_yn(result.memory.reexplain[c])}"
        b_act = f"{_mastery(result.baseline.mastery.get(c))} -> {_yn(result.baseline.reexplain[c])}"
        rows.append(f"  {c:<13} {is_m:^8}   {m_act:<28}   {b_act}")
    return "\n".join(rows)


def _metric_table(result: EvalResult) -> str:
    mem, base = result.memory, result.baseline
    n_mastered = len(result.mastered_concepts)
    n_probes = len(result.probes)
    rows = [
        f"  {'metric':<40}{'memory':>12}{'baseline':>12}",
        "  " + "-" * 64,
        f"  {'re-explain rate of mastered concepts':<40}"
        f"{_pct(mem.reexplain_rate_of_mastered):>12}"
        f"{_pct(base.reexplain_rate_of_mastered):>12}",
        f"  {f'prior-session recall hits (of {n_probes})':<40}"
        f"{mem.prior_session_recall_hits:>12}"
        f"{base.prior_session_recall_hits:>12}",
    ]
    return "\n".join(rows), n_mastered, n_probes


def _headline(result: EvalResult) -> str:
    mem, base = result.memory, result.baseline
    mastered = result.mastered_concepts
    n = len(mastered)
    # How many mastered concepts the baseline needlessly re-explained but memory did not.
    saved = [
        c for c in mastered if base.reexplain.get(c) and not mem.reexplain.get(c)
    ]
    reduction = base.reexplain_rate_of_mastered - mem.reexplain_rate_of_mastered
    n_probes = len(result.probes)
    lines = [
        f"With memory, the tutor re-explained mastered material {_pct(reduction)} less "
        f"({_pct(mem.reexplain_rate_of_mastered)} vs {_pct(base.reexplain_rate_of_mastered)} "
        f"of {n} mastered concept(s): {', '.join(mastered) or 'none'}).",
        f"It recalled prior-session context "
        f"{mem.prior_session_recall_hits}/{n_probes} times vs the baseline's "
        f"{base.prior_session_recall_hits}/{n_probes}.",
    ]
    if saved:
        lines.append(
            f"Concretely, memory skipped re-explaining: {', '.join(saved)} "
            f"(already mastered, but pushed out of the baseline's last-"
            f"{result.baseline_window} window)."
        )
    return "\n".join(lines)


def format_report(result: EvalResult) -> str:
    metric_block, _n_mastered, _n_probes = _metric_table(result)
    parts = [
        "=" * 88,
        "Engram ablation: synthesized graph memory vs. last-N raw events",
        "=" * 88,
        f"learner: {result.learner_id}   persona: {result.persona}",
        f"mastery_threshold: {result.mastery_threshold}   "
        f"baseline_window: last {result.baseline_window} events",
        "",
        "Per-probe tutor decision (would it re-explain at the next session?):",
        _probe_table(result),
        "",
        "Metrics (memory should re-explain mastered material LESS, recall MORE):",
        metric_block,
        "",
        "HEADLINE:",
        _headline(result),
        "=" * 88,
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scenario: Path | None = Path(argv[0]) if argv else None

    result = asyncio.run(run_eval(scenario))
    print(format_report(result))

    # Non-zero exit if the demonstration fails to hold (useful as a smoke check).
    ok = (
        result.memory.reexplain_rate_of_mastered
        < result.baseline.reexplain_rate_of_mastered
        and result.memory.prior_session_recall_hits
        >= result.baseline.prior_session_recall_hits
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
