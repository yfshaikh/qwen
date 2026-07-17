"""CLI for the eval harness:  python -m engram.eval <gen|sweep|demo|report|run|repair> ...

gen     <scenario.yaml>                       -> writes eval/fixtures/<id>.json
sweep   <scenario.yaml> <fixture.json> --grid <grid.yaml> [--tier 1|2]  -> sweep report
demo    <scenario.yaml> <fixture.json>        -> ON vs baseline headline
report  <results.json>                        -> re-render a saved sweep result
run     <scenario.yaml> [--checks a,b] [--budget-usd F] [--against R] [--tolerance F]
        -> execute a scenario run, apply checks, compare to a baseline
repair  --learner X                           -> retroactively merge duplicate nodes
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import yaml

from engram.core.engram import Engram
from engram.eval import fixtures, report
from engram.eval.arms import run_behavior_arm
from engram.eval.fixtures import load_graph_into
from engram.eval.metrics import aggregate_behavior, judge_turn
from engram.eval.scenario import load_scenario
from engram.eval.sweep import run_tier1_sweep, run_tier2_sweep


async def _gen(args) -> None:
    eng = Engram.from_env()
    await eng.connect()
    try:
        sc = load_scenario(args.scenario)
        fx = await fixtures.generate_fixture(eng, sc, runid="gen")
        out = Path("eval/fixtures") / f"{sc.id}.json"
        fixtures.save_fixture(out, scenario_id=fx["scenario_id"], sessions=fx["sessions"], graph=fx["graph"])
        print(f"wrote {out}  ({len(fx['graph']['nodes'])} nodes)")
    finally:
        await eng.aclose()


async def _sweep(args) -> None:
    eng = Engram.from_env()
    await eng.connect()
    try:
        sc = load_scenario(args.scenario)
        fx = fixtures.load_fixture(args.fixture)
        grid = yaml.safe_load(Path(args.grid).read_text())
        if args.tier == 2:
            result = await run_tier2_sweep(eng, fx["sessions"], sc.probes, grid,
                                           target=args.target)
        else:
            result = await run_tier1_sweep(eng.storage, eng.embedder, fx["graph"],
                                           sc.probes, grid, target=args.target)
        out = Path("eval/reports") / f"{sc.id}-sweep.md"
        out.write_text(report.render_markdown(result["rows"], target=args.target, best=result["best"]))
        (Path("eval/reports") / f"{sc.id}-sweep.csv").write_text(report.render_csv(result["rows"]))
        print(report.render_markdown(result["rows"], target=args.target, best=result["best"]))
        print(f"\nwrote {out}")
    finally:
        await eng.aclose()


async def _demo(args) -> None:
    eng = Engram.from_env()
    await eng.connect()
    learner_id = None
    try:
        sc = load_scenario(args.scenario)
        fx = fixtures.load_fixture(args.fixture)
        learner_turns = [t["content"] for s in fx["sessions"] for t in s["turns"] if t["role"] == "user"]
        learner_id = f"eval:{sc.id}:demo-{uuid.uuid4().hex[:8]}"
        await load_graph_into(eng.storage, fx["graph"], learner_id)
        on = await run_behavior_arm(eng, learner_turns, learner_id, "on")
        base = await run_behavior_arm(eng, learner_turns, learner_id, "baseline")
        on_j = [await judge_turn(eng.llm, r, sc.hidden_state) for r in on]
        base_j = [await judge_turn(eng.llm, r, sc.hidden_state) for r in base]
        print(report.headline(aggregate_behavior(on_j), aggregate_behavior(base_j)))
    finally:
        if learner_id:
            await eng.storage.delete_learner(learner_id)
        await eng.aclose()


async def _repair(args) -> None:
    eng = Engram.from_env()
    await eng.connect()
    try:
        out = await eng.repair_merges(args.learner)
        for p in out["pairs"]:
            print(f"merged {p}")
        print(f"merged={out['merged']} skipped={out['skipped']}")
    finally:
        await eng.aclose()


async def _run_repeat(eng, sc, args) -> None:
    """run --repeat N: same scenario N times, majority-of-N verdict per check.

    This is how a fix gets verified on checks that flip run-to-run (measured:
    `concepts`/`knowledge_update` flip on byte-identical input). A single run
    remains the default for quick iteration; the gate is the repeat form.
    """
    from engram.eval import runs as run_store
    from engram.eval.aggregate import aggregate, gate, render, scored
    from engram.eval.clock import SimClock
    from engram.eval.runner import execute_many

    def new_dir():
        _, run_dir = run_store.new_run(sc.id)
        return run_dir

    def on_done(r: dict) -> None:
        failed = [c["name"] for c in r.get("checks", []) if not c["passed"]]
        print(f"  {r['run_id']}  status={r['status']}  "
              f"${r['cost']['usd']:.4f}"
              + (f"  failed: {', '.join(failed)}" if failed else ""),
              file=sys.stderr, flush=True)

    print(f"running {sc.id} x{args.repeat} (concurrency {args.concurrency})",
          file=sys.stderr, flush=True)
    results = await execute_many(
        eng, sc, new_dir, n=args.repeat,
        checks=args.checks.split(",") if args.checks else None,
        concurrency=args.concurrency,
        max_cost_usd=args.budget_usd, clock_factory=SimClock, on_done=on_done)

    by = aggregate(results)
    print(render(by, n_asked=args.repeat, n_scored=len(scored(results))))
    print(f"total cost=${sum(r['cost']['usd'] for r in results):.4f}")
    raise SystemExit(0 if gate(by, args.repeat) else 1)


async def _run(args) -> None:
    from engram.eval import runs as run_store
    from engram.eval.clock import SimClock
    from engram.eval.regression import compare, flatten_metrics
    from engram.eval.runner import execute_run

    eng = Engram.from_env()
    await eng.connect()
    try:
        sc = load_scenario(args.scenario)
        if args.repeat > 1:
            if args.against:
                raise SystemExit("--against does not compose with --repeat")
            await _run_repeat(eng, sc, args)
            return  # unreachable — _run_repeat exits; keeps control flow obvious
        _, run_dir = run_store.new_run(sc.id)
        checks = args.checks.split(",") if args.checks else None

        turns = {"n": 0}

        def emit(e: dict) -> None:
            # persist every event, and print a live line to stderr so a long
            # real-LLM run isn't a silent black box.
            run_store.append_event(run_dir, e)
            t = e.get("type")
            if t == "session":
                turns["n"] = 0
                print(f"session {e['n']} (gap {e['gap_days']:g}d) ",
                      end="", file=sys.stderr, flush=True)
            elif t == "turn":
                turns["n"] += 1
                print(".", end="", file=sys.stderr, flush=True)
            elif t == "consolidated":
                r = e["report"]
                print(f" consolidated (+{r['nodes_created']} nodes, {r['merged']} merged,"
                      f" {r['forgotten']} forgotten)", file=sys.stderr, flush=True)
            elif t == "check_start":
                extra = " (replays turns — slow, spends LLM)" if e.get("needs") == "live" else ""
                print(f"  running {e['name']}{extra}...", file=sys.stderr, flush=True)
            elif t == "check":
                print(f"  check {e['name']}: {'pass' if e['passed'] else 'FAIL'}",
                      file=sys.stderr, flush=True)
            elif t == "error":
                print(f"  ! {e['message']}", file=sys.stderr, flush=True)
            elif t == "status" and e.get("status") not in (None, "running"):
                print(f"[{e['status']}]", file=sys.stderr, flush=True)

        print(f"running {sc.id} -> {run_dir}", file=sys.stderr, flush=True)
        data = await execute_run(
            eng, sc, run_dir, checks=checks, max_cost_usd=args.budget_usd,
            clock=SimClock(), emit=emit)
        for c in data["checks"]:
            mark = "PASS" if c["passed"] else "FAIL"
            print(f"[{mark}] {c['name']}  {c['metrics']}")
            for d in (c["details"] or [])[:5]:
                print(f"       - {d}")
        print(f"status={data['status']}  cost=${data['cost']['usd']:.4f}  dir={run_dir}")
        failed = data["status"] != "passed"
        if args.against:
            base = run_store.read_run(_resolve_run_dir(args.against))
            regs = compare(flatten_metrics(data), flatten_metrics(base), args.tolerance)
            if not regs and not (flatten_metrics(data).keys() & flatten_metrics(base).keys()):
                print("WARNING: no shared metrics with baseline; regression compare is a no-op")
            for r in regs:
                print(f"REGRESSION {r['metric']}: {r['current']} vs baseline {r['baseline']}")
            failed = failed or bool(regs)
        raise SystemExit(1 if failed else 0)
    finally:
        await eng.aclose()


def _resolve_run_dir(ref: str) -> Path:
    p = Path(ref)
    if p.is_file() and p.name == "run.json":
        return p.parent
    if p.is_dir():
        return p
    hits = [d for d in Path("eval/runs").rglob("run.json") if d.parent.name.endswith(ref)]
    if len(hits) != 1:
        raise SystemExit(f"--against {ref!r}: {'ambiguous' if hits else 'not found'}: "
                         f"{[str(h.parent) for h in hits]}")
    return hits[0].parent


def _report(args) -> None:
    data = json.loads(Path(args.results).read_text())
    print(report.render_markdown(data["rows"], target=data.get("target", "node_hit_rate"),
                                 best=data.get("best", {})))


def main() -> None:
    ap = argparse.ArgumentParser(prog="engram.eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("scenario")
    s = sub.add_parser("sweep")
    s.add_argument("scenario")
    s.add_argument("fixture")
    s.add_argument("--grid", required=True)
    s.add_argument("--target", default="node_hit_rate")
    s.add_argument("--tier", type=int, choices=(1, 2), default=1)
    d = sub.add_parser("demo")
    d.add_argument("scenario")
    d.add_argument("fixture")
    r = sub.add_parser("report")
    r.add_argument("results")
    rn = sub.add_parser("run")
    rn.add_argument("scenario")
    rn.add_argument("--checks")
    rn.add_argument("--budget-usd", type=float, default=None)
    rn.add_argument("--against")
    rn.add_argument("--tolerance", type=float, default=0.0)
    rn.add_argument("--repeat", type=int, default=1,
                    help="run N times and gate on majority-of-N per check; "
                         "required to verify fixes on checks that flip run-to-run")
    rn.add_argument("--concurrency", type=int, default=2)
    rp = sub.add_parser("repair")
    rp.add_argument("--learner", required=True)
    args = ap.parse_args()
    if args.cmd == "gen":
        asyncio.run(_gen(args))
    elif args.cmd == "sweep":
        asyncio.run(_sweep(args))
    elif args.cmd == "demo":
        asyncio.run(_demo(args))
    elif args.cmd == "report":
        _report(args)
    elif args.cmd == "run":
        asyncio.run(_run(args))
    elif args.cmd == "repair":
        asyncio.run(_repair(args))


if __name__ == "__main__":
    main()
