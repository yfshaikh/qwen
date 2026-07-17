"""Run orchestration. Builds a RUN-SCOPED Engram (shared storage/embedder, metered
LLM, sim clock) — never mutates the base instance, which may be serving real
traffic. Sessions: advance clock -> student/tutor turns -> ingest -> consolidate ->
snapshot. Then checks. Learner cleanup is unconditional."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import engram.eval.checks  # noqa: F401  (register built-in checks)
from engram.core.engram import Engram
from engram.core.models import LearningEvent
from engram.core.tokens import heuristic_token_count
from engram.eval.arms import _tutor_reply
from engram.eval.fixtures import snapshot_graph, student_prompt
from engram.eval.registry import EvalContext, get_check, run_check
from engram.eval.runs import write_run
from engram.eval.scenario import Scenario


class BudgetExceeded(RuntimeError):
    pass


class MeteredLLM:
    def __init__(self, inner: Any, *, price_in_per_m: float = 0.0,
                 price_out_per_m: float = 0.0, max_cost_usd: float | None = None) -> None:
        self._inner = inner
        self._pin = price_in_per_m
        self._pout = price_out_per_m
        self._cap = max_cost_usd
        self._by_role: dict[str, dict[str, float]] = {}

    def _tally(self, role: str, tin: int, tout: int) -> None:
        r = self._by_role.setdefault(role, {"tokens_in": 0, "tokens_out": 0})
        r["tokens_in"] += tin
        r["tokens_out"] += tout
        if self._cap is not None and self.cost["usd"] > self._cap:
            raise BudgetExceeded(f"run cost ${self.cost['usd']:.4f} exceeds cap ${self._cap}")

    @property
    def cost(self) -> dict:
        tin = sum(r["tokens_in"] for r in self._by_role.values())
        tout = sum(r["tokens_out"] for r in self._by_role.values())
        usd = tin / 1e6 * self._pin + tout / 1e6 * self._pout
        return {"tokens_in": tin, "tokens_out": tout, "usd": usd,
                "by_role": {k: dict(v) for k, v in self._by_role.items()}}

    async def complete(self, role: str, messages: list, schema: dict | None = None):
        out = await self._inner.complete(role, messages, schema)
        u = out.usage or {}
        self._tally(role, int(u.get("prompt_tokens") or 0),
                    int(u.get("completion_tokens") or 0))
        return out

    async def stream(self, role: str, messages: list):
        # streams carry no usage; approximate output with the heuristic counter
        total = 0
        async for delta in self._inner.stream(role, messages):
            total += heuristic_token_count(delta)
            yield delta
        self._tally(role, 0, total)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def execute_many(
    base_eng: Any, scenario: Scenario, new_run_dir: Callable[[], Path], *,
    n: int, checks: list[str] | None = None, concurrency: int = 2,
    max_cost_usd: float | None = None,
    clock_factory: Callable[[], Any] | None = None,
    emit: Callable[[dict], None] | None = None,
    on_done: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Run the same scenario n times; never raises for a single bad run.

    Runs share one Engram (one pool, one LLM client); each gets its own run dir,
    throwaway learner, and fresh clock (a shared clock would leak gap_days
    between concurrent runs and silently change the decay math). Concurrency is
    capped because providers rate-limit, and a 429 mid-run pollutes the sample
    with a fake 'error' verdict. A run that raises past execute_run's own
    handling is returned as status='crashed' with empty checks — aggregate.py
    counts it against the majority rather than dropping it from the sample.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one() -> dict:
        async with sem:
            run_dir: Path | None = None
            try:
                run_dir = Path(new_run_dir())
                data = await execute_run(
                    base_eng, scenario, run_dir, checks=checks,
                    max_cost_usd=max_cost_usd,
                    clock=clock_factory() if clock_factory else None, emit=emit)
            except Exception as exc:  # noqa: BLE001 — one bad run must not kill the sample
                data = {"run_id": run_dir.name if run_dir else "?",
                        "status": "crashed",
                        "error": f"{type(exc).__name__}: {exc}", "checks": [],
                        "cost": {"usd": 0.0}}
            if on_done:
                on_done(data)
            return data

    return list(await asyncio.gather(*[one() for _ in range(n)]))


async def execute_run(
    base_eng: Any, scenario: Scenario, run_dir: Path, *,
    checks: list[str] | None = None, max_cost_usd: float | None = None,
    price_in_per_m: float | None = None, price_out_per_m: float | None = None,
    clock: Any = None, emit: Callable[[dict], None] | None = None,
) -> dict:
    run_dir = Path(run_dir)
    (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    emit = emit or (lambda e: None)

    s = getattr(base_eng, "settings", None)
    pin = price_in_per_m if price_in_per_m is not None else getattr(s, "eval_price_in_per_m", 0.0)
    pout = price_out_per_m if price_out_per_m is not None else getattr(s, "eval_price_out_per_m", 0.0)
    metered = MeteredLLM(base_eng.llm, price_in_per_m=pin, price_out_per_m=pout,
                         max_cost_usd=max_cost_usd)
    # Engram no longer reads recall/keeper knobs off `settings` at call time —
    # carry base_eng's already-resolved configs forward so any env-driven
    # ENGRAM_RECALL_*/ENGRAM_KEEPER_* override still reaches the run-scoped clone.
    run_eng = Engram(storage=base_eng.storage, llm=metered, embedder=base_eng.embedder,
                     settings=s, now=clock,
                     recall=getattr(base_eng, "_recall", None),
                     keeper=getattr(base_eng, "_keeper", None))

    learner_id = f"eval:{scenario.id}:run-{run_dir.name.split('-')[-1]}"
    check_names = checks if checks is not None else [c.name for c in scenario.checks]
    data: dict = {
        "run_id": run_dir.name.split("-")[-1], "scenario_id": scenario.id,
        "status": "running", "started_at": _utcnow_iso(), "finished_at": None,
        "checks_requested": check_names, "checks": [], "cost": metered.cost,
        "error": None, "learner_deleted": False,
    }
    write_run(run_dir, data)
    emit({"type": "status", "status": "running"})
    if max_cost_usd is not None and pin == 0.0 and pout == 0.0:
        emit({"type": "error",
              "message": "budget cap set but ENGRAM_EVAL_PRICE_* unconfigured; cap cannot trip"})
    # A frozen transcript pins the input, which leaves SAMPLING as the only source
    # of run-to-run variance. Unpinned, the fixture still runs but is not a gate —
    # and silently reporting a number nobody can reproduce is how a coin flip gets
    # mistaken for a verified fix. Same shape as the budget-cap warning above.
    if scenario.frozen:
        temp_for = getattr(s, "temperature_for", None)
        unpinned = [r for r in ("extractor", "reflector")
                    if temp_for is None or temp_for(r) is None]
        if unpinned:
            emit({"type": "error",
                  "message": f"frozen transcript but {'/'.join(unpinned)} temperature "
                             f"unpinned (ENGRAM_TEMPERATURE_{unpinned[0].upper()}=0); run is "
                             "not reproducible and must not be used as a gate"})

    snapshots: list[dict] = []
    transcript: list[dict] = []
    try:
        # Fail fast on unknown checks BEFORE spending any LLM tokens.
        resolved = [get_check(n) for n in check_names]

        history: list[dict] = []
        for si, session in enumerate(scenario.sessions):
            if session.gap_days and clock is not None:
                clock.advance(days=session.gap_days)
            emit({"type": "session", "n": si, "gap_days": session.gap_days,
                  "frozen": session.frozen})
            for turn_i in range(session.turns):
                if session.frozen:
                    # Replay. No student call, no tutor call, no recall — the reply
                    # is fixed text, so recall's output would be computed and
                    # discarded. Recall is exercised by `recall_probes` instead.
                    assert session.transcript is not None  # guaranteed by .frozen
                    user = session.transcript[turn_i * 2]["content"]
                    reply = session.transcript[turn_i * 2 + 1]["content"]
                    history.append({"role": "user", "content": user})
                    transcript.append({"role": "user", "content": user, "session": si})
                    emit({"type": "turn", "role": "user", "session": si})
                    history.append({"role": "assistant", "content": reply})
                    transcript.append({"role": "assistant", "content": reply, "session": si})
                    emit({"type": "turn", "role": "assistant", "session": si})
                else:
                    lines = "\n".join(f"{h['role']}: {h['content']}" for h in history)
                    out = await metered.complete("student",
                                                 student_prompt(scenario, session.intent, lines))
                    user = (out.text or "").strip()
                    history.append({"role": "user", "content": user})
                    transcript.append({"role": "user", "content": user, "session": si})
                    emit({"type": "turn", "role": "user", "session": si})
                    context = (await run_eng.recall(learner_id, user, None)).text_block
                    reply = await _tutor_reply(run_eng, context, history)
                    history.append({"role": "assistant", "content": reply})
                    transcript.append({"role": "assistant", "content": reply, "session": si})
                    emit({"type": "turn", "role": "assistant", "session": si})
                await run_eng.ingest([
                    LearningEvent(learner_id=learner_id, type="utterance", text=user),
                    LearningEvent(learner_id=learner_id, type="tutor_explanation", text=reply),
                ])
            # consolidate() only — deliberately NOT repair_merges (roadmap §4.4
            # asked for this decision to be recorded). repair is an admin/CLI
            # verb outside the production write path; running it here would
            # measure a pipeline production doesn't run, and would mask the
            # same-batch dedup bugs (`tmp-` hole) the frozen checks exist to
            # catch. When repair becomes part of the write path, add it here.
            report = await run_eng.consolidate(learner_id)
            graph = await snapshot_graph(run_eng.storage, learner_id, include_forgotten=True)
            snap = {"session": si,
                    "sim_ts": clock().isoformat() if clock is not None else _utcnow_iso(),
                    "graph": graph,
                    "report": {"processed_events": report.processed_events,
                               "nodes_created": report.nodes_created,
                               "nodes_updated": report.nodes_updated,
                               "edges_created": report.edges_created,
                               "merged": report.merged, "forgotten": report.forgotten}}
            snapshots.append(snap)
            (run_dir / "snapshots" / f"session-{si}.json").write_text(
                json.dumps(snap, default=str))
            emit({"type": "consolidated", "session": si, "report": snap["report"]})

        with open(run_dir / "transcript.jsonl", "w") as f:
            for t in transcript:
                f.write(json.dumps(t) + "\n")

        results = []
        for rc in resolved:
            emit({"type": "check_start", "name": rc.name, "needs": rc.needs})
            spec_params = next((c.params for c in scenario.checks if c.name == rc.name), {})
            ctx = EvalContext(eng=run_eng, scenario=scenario, learner_id=learner_id,
                              snapshots=snapshots, transcript=transcript, clock=clock,
                              params=spec_params)
            res = await run_check(rc, ctx)
            results.append(res)
            emit({"type": "check", "name": res.name, "passed": res.passed})
        data["checks"] = [r.to_dict() for r in results]
        data["status"] = "passed" if all(r.passed for r in results) else "failed"
    except BudgetExceeded as exc:
        data["status"] = "over_budget"
        data["error"] = str(exc)
        emit({"type": "error", "message": str(exc)})
    except asyncio.CancelledError:
        data["status"] = "cancelled"
        raise  # cooperative: finally still runs, caller sees the cancel
    except Exception as exc:  # noqa: BLE001 — run.json IS the error report
        data["status"] = "error"
        data["error"] = f"{type(exc).__name__}: {exc}"
        emit({"type": "error", "message": data["error"]})
    finally:
        try:
            await base_eng.storage.delete_learner(learner_id)
            data["learner_deleted"] = True
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            data["learner_deleted"] = False
        data["cost"] = metered.cost
        data["finished_at"] = _utcnow_iso()
        # ponytail: inline transcript in run.json; split out if runs grow long
        data["transcript"] = transcript
        write_run(run_dir, data)
        emit({"type": "status", "status": data["status"]})
    return data
