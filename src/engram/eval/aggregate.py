"""N-run verdict aggregation — the eval's answer to a nondeterministic extractor.

A frozen transcript pins the eval's INPUT, not its VERDICT: measured across 15+
runs of em-frozen-v1, `concepts` and `knowledge_update` flip on byte-identical
sessions (~1-in-15), `preferences` more often. On a check that flips, a single
run cannot verify a fix — the fix-loop sees a lucky pass and declares victory.

So the gate is majority-of-N: a check passes the gate iff it passes a strict
majority of the runs ASKED for. Runs that crash or produce no verdicts count
AGAINST the majority — a gate must not pass on a sample it didn't get (the
first live variance batch lost 3 of 5 runs to 429s; treating survivors as the
sample announced stability off 2 data points).

Pure functions over run dicts (the shape `execute_run` returns / run.json
holds), so all of this is testable without an LLM in the loop.
"""
from __future__ import annotations

from dataclasses import dataclass


def scored(runs: list[dict]) -> list[dict]:
    """Runs that actually produced verdicts. Budget-busts and 429s have an
    error status and an empty checks list — they are lost sample, not evidence."""
    return [r for r in runs if r.get("status") != "crashed" and r.get("checks")]


@dataclass(slots=True)
class CheckAgg:
    name: str
    passes: int
    n: int  # scored runs that reported this check

    @property
    def flaky(self) -> bool:
        return 0 < self.passes < self.n

    def gate_passed(self, n_asked: int) -> bool:
        return self.passes * 2 > n_asked


def aggregate(runs: list[dict]) -> dict[str, CheckAgg]:
    by: dict[str, CheckAgg] = {}
    for r in scored(runs):
        for c in r.get("checks", []):
            agg = by.setdefault(c["name"], CheckAgg(name=c["name"], passes=0, n=0))
            agg.n += 1
            agg.passes += bool(c["passed"])
    return by


def gate(by: dict[str, CheckAgg], n_asked: int) -> bool:
    """True iff every check passes a strict majority of the ASKED runs."""
    return bool(by) and all(a.gate_passed(n_asked) for a in by.values())


def render(by: dict[str, CheckAgg], *, n_asked: int, n_scored: int) -> str:
    lines = [f"aggregate over {n_scored}/{n_asked} scored runs "
             "(lost runs count against the majority):"]
    for name in sorted(by):
        a = by[name]
        mark = "PASS" if a.gate_passed(n_asked) else "FAIL"
        flake = "  ⚠ FLAKY — verdict differs across identical runs" if a.flaky else ""
        lines.append(f"[{mark}] {name}  {a.passes}/{a.n} runs passed{flake}")
    return "\n".join(lines)
