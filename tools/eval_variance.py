"""Run one scenario N times and report WHICH CHECKS FLIP.

    python tools/eval_variance.py eval/scenarios/em-frozen-v1.yaml -n 5

WHY THIS EXISTS
A frozen transcript pins the eval's INPUT. It does not pin its VERDICT. Three runs
of em-frozen-v1 (roadmap §7) showed `concepts` and `knowledge_update` flipping on
byte-identical sessions: the same correct answer was attributed to a different
concept each time, taking Lenz's law's mastery from 0.55 to 0.00 and
`knowledge_update` from pass to fail. Sampling at temperature=0 did not prevent it.

That matters because the plan is to hand an agent a list of bugs and let it verify
its own fixes against this eval. **On a check that flips, a single run cannot
verify anything** — the agent sees a lucky pass and declares victory, or a random
fail and "adjusts accordingly", making the code worse chasing a ghost. This script
measures how much of the signal is real before anything depends on it.

It answers exactly one question: for each check, is the verdict stable across
identical runs? A check at 5/5 or 0/5 is trustworthy. Anything between is a coin
flip and needs N-run aggregation before it can gate a fix.

Runs share one Engram (one asyncpg pool, one LLM client) and each gets its own
throwaway learner + SimClock, so they cannot collide. Concurrency is capped because
providers rate-limit: 5 runs x 3 sessions is a burst, and a 429 mid-run reports as
an `error` verdict that would pollute the very measurement being taken.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engram.core.engram import Engram
from engram.eval import runs as run_store
from engram.eval.clock import SimClock
from engram.eval.runner import execute_run
from engram.eval.scenario import Scenario, load_scenario


async def _one(eng: Any, sc: Scenario, budget: float | None,
               sem: asyncio.Semaphore) -> dict:
    async with sem:
        run_id, run_dir = run_store.new_run(sc.id)
        print(f"  start {run_id}", file=sys.stderr, flush=True)
        try:
            # Each run gets a fresh SimClock: execute_run hands it to the run-scoped
            # Engram and the sessions advance it, so a shared one would leak gap_days
            # between concurrent runs and silently change the decay math.
            data = await execute_run(eng, sc, run_dir, max_cost_usd=budget,
                                     clock=SimClock())
        except Exception as exc:  # noqa: BLE001 — one bad run must not kill the sample
            print(f"  ERROR {run_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return {"run_id": run_id, "status": "crashed",
                    "error": f"{type(exc).__name__}: {exc}", "checks": [],
                    "cost": {"usd": 0.0}}
        print(f"  done  {run_id}  status={data['status']}  "
              f"${data['cost']['usd']:.4f}", file=sys.stderr, flush=True)
        return data


def _report(sc: Scenario, results: list[dict], n: int) -> str:
    ok = [r for r in results if r["status"] != "crashed"]
    by_check: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        for c in r.get("checks", []):
            by_check[c["name"]].append(c)

    lines: list[str] = [
        f"# Eval variance — {sc.id} x {n}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Runs: {', '.join(r['run_id'] for r in results)}",
        f"Total cost: ${sum(r['cost']['usd'] for r in results):.4f}",
        f"Crashed: {len(results) - len(ok)}",
        "",
        "The question this answers: **is each check's verdict stable across "
        "identical runs?** 5/5 or 0/5 is trustworthy. Anything between is a coin "
        "flip and cannot verify a fix on its own.",
        "",
        "## Verdict stability",
        "",
        "| check | passed | verdict |",
        "|---|---|---|",
    ]

    flipping: list[str] = []
    for name in sorted(by_check):
        got = by_check[name]
        npass = sum(1 for c in got if c["passed"])
        if npass == len(got):
            verdict = "✅ stable pass"
        elif npass == 0:
            verdict = "✅ stably RED — trustworthy, act on it"
        else:
            verdict = "⚠️ **FLIPS — not a gate**"
            flipping.append(name)
        lines.append(f"| `{name}` | {npass}/{len(got)} | {verdict} |")

    lines += ["", "## Headline", ""]
    if not ok:
        lines.append("**Every run crashed.** Nothing measured.")
    elif flipping:
        lines.append(
            f"**{len(flipping)} of {len(by_check)} checks flip**: "
            + ", ".join(f"`{f}`" for f in flipping) + ".")
        lines.append("")
        lines.append(
            "A fix cannot be verified by a single run on these. Either aggregate N "
            "runs per verdict, or fix the underlying nondeterminism first "
            "(roadmap §3.1 fix #1 — give the extractor the existing concepts so "
            "attribution has an anchor instead of being re-decided every session).")
    else:
        lines.append(
            f"**All {len(by_check)} checks are stable across {len(ok)} identical "
            "runs.** The eval can gate a fix-loop.")

    # Distinct failure modes per flipping check: identical text across runs means one
    # bug, differing text means the failure ITSELF is nondeterministic.
    if flipping:
        lines += ["", "## Flipping checks — distinct failure modes", ""]
        for name in flipping:
            lines.append(f"### `{name}`")
            seen: dict[str, int] = defaultdict(int)
            for c in by_check[name]:
                key = "PASS" if c["passed"] else "\n".join(
                    d for d in c["details"] if not d.startswith("unmatched"))
                seen[key] += 1
            for key, count in sorted(seen.items(), key=lambda x: -x[1]):
                lines.append(f"- **x{count}** — {'PASS' if key == 'PASS' else ''}")
                if key != "PASS":
                    for d in key.splitlines():
                        lines.append(f"    - {d}")
            lines.append("")

    # Metric spread. A metric that varies while its verdict holds is early warning:
    # the check is stable today by luck, not by construction.
    lines += ["", "## Metric spread", "",
              "| check | metric | min | max | spread |", "|---|---|---|---|---|"]
    for name in sorted(by_check):
        agg: dict[str, list[float]] = defaultdict(list)
        for c in by_check[name]:
            for k, v in (c.get("metrics") or {}).items():
                agg[k].append(float(v))
        for k, vals in sorted(agg.items()):
            lo, hi = min(vals), max(vals)
            spread = "—" if lo == hi else f"**{hi - lo:.3f}**"
            mean = statistics.fmean(vals)
            lines.append(f"| `{name}` | {k} | {lo:.3f} | {hi:.3f} | {spread} "
                         f"(mean {mean:.3f}) |")

    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario", help="path to a scenario YAML")
    ap.add_argument("-n", type=int, default=5, help="number of identical runs")
    ap.add_argument("--budget-usd", type=float, default=0.10,
                    help="per-run cost cap (needs ENGRAM_EVAL_PRICE_* set)")
    ap.add_argument("--concurrency", type=int, default=3,
                    help="max simultaneous runs; providers rate-limit, and a 429 "
                         "mid-run pollutes the sample with a fake 'error' verdict")
    ap.add_argument("-o", "--out", default=None,
                    help="report path (default eval/runs/variance-<scenario>.md)")
    args = ap.parse_args()

    sc = load_scenario(args.scenario)
    if not sc.frozen:
        print(f"WARNING: {sc.id} is not frozen — its sessions are LLM-generated, so "
              "this measures the student simulator's variance too, not the "
              "extractor's. The number will be meaningless for gating.",
              file=sys.stderr)

    out = Path(args.out or f"eval/runs/variance-{sc.id}.md")
    out.parent.mkdir(parents=True, exist_ok=True)

    eng = Engram.from_env()
    await eng.connect()
    try:
        sem = asyncio.Semaphore(max(1, args.concurrency))
        print(f"running {sc.id} x{args.n} (concurrency {args.concurrency})",
              file=sys.stderr, flush=True)
        results = await asyncio.gather(
            *[_one(eng, sc, args.budget_usd, sem) for _ in range(args.n)])
    finally:
        await eng.aclose()

    report = _report(sc, list(results), args.n)
    out.write_text(report)
    print(report)
    print(f"\nwrote {out}", file=sys.stderr)

    # Exit 1 if any check flips: this script's whole purpose is answering "can a
    # single run verify a fix?", and a flip means no.
    ok = [r for r in results if r["status"] != "crashed"]
    by_check: dict[str, list[bool]] = defaultdict(list)
    for r in ok:
        for c in r.get("checks", []):
            by_check[c["name"]].append(bool(c["passed"]))
    flips = any(0 < sum(v) < len(v) for v in by_check.values())
    return 1 if (flips or not ok) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
