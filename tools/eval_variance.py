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

from engram.core.engram import Engram
from engram.eval import runs as run_store
from engram.eval.aggregate import scored as _scored
from engram.eval.clock import SimClock
from engram.eval.runner import execute_many
from engram.eval.scenario import Scenario, load_scenario


def _report(sc: Scenario, results: list[dict], n: int) -> str:
    ok = _scored(results)
    lost = [r for r in results if r not in ok]
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
        f"**Scored {len(ok)} of {n} runs.**"
        + ("" if not lost else
           " Excluded (produced no verdicts — NOT evidence of stability): "
           + ", ".join(f"{r['run_id']} ({r['status']})" for r in lost)),
        "",
        "The question this answers: **is each check's verdict stable across "
        f"identical runs?** {len(ok)}/{len(ok)} or 0/{len(ok)} is trustworthy. "
        "Anything between is a coin flip and cannot verify a fix on its own.",
        "",
        f"⚠️ Resolution: {len(ok)} runs can only see flip rates ≥ ~1/{len(ok)}. "
        "A 'stable' verdict here is stability *at this sample size*, not proof — "
        "`concepts` looked stably red at n=4 on 2026-07-15 and flips at ~1/15 "
        "in the full run history.",
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
    if len(ok) < 2:
        lines.append(
            f"**Only {len(ok)} of {n} runs produced verdicts — variance is "
            "unmeasurable.** Nothing below is a stability claim. Rerun; if these "
            "were 429s, the token-per-minute budget is the constraint and "
            "concurrency cannot buy its way out of it.")
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
            f"**All {len(by_check)} checks held the same verdict across {len(ok)} "
            "identical runs.**"
            + (" The eval can gate a fix-loop." if len(ok) >= n else
               f" But {n - len(ok)} run(s) were lost, so this is a {len(ok)}-sample "
               "result — weaker than asked for."))

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

    def _new_dir():
        _, run_dir = run_store.new_run(sc.id)
        print(f"  start {run_dir.name}", file=sys.stderr, flush=True)
        return run_dir

    def _on_done(r: dict) -> None:
        print(f"  done  {r['run_id']}  status={r['status']}  "
              f"${r['cost']['usd']:.4f}", file=sys.stderr, flush=True)

    eng = Engram.from_env()
    await eng.connect()
    try:
        print(f"running {sc.id} x{args.n} (concurrency {args.concurrency})",
              file=sys.stderr, flush=True)
        results = await execute_many(
            eng, sc, _new_dir, n=args.n, concurrency=args.concurrency,
            max_cost_usd=args.budget_usd, clock_factory=SimClock,
            on_done=_on_done)
    finally:
        await eng.aclose()

    report = _report(sc, list(results), args.n)
    out.write_text(report)
    print(report)
    print(f"\nwrote {out}", file=sys.stderr)

    # Exit 1 if any check flips: this script's whole purpose is answering "can a
    # single run verify a fix?", and a flip means no. Also exit 1 on a short sample —
    # "no flips seen" across 2 runs when 5 were asked for is an absence of evidence,
    # and a 0 here would be read as evidence of absence.
    ok = _scored(results)
    by_check: dict[str, list[bool]] = defaultdict(list)
    for r in ok:
        for c in r.get("checks", []):
            by_check[c["name"]].append(bool(c["passed"]))
    flips = any(0 < sum(v) < len(v) for v in by_check.values())
    return 1 if (flips or len(ok) < args.n) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
