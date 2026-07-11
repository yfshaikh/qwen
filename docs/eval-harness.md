# Eval harness

`src/engram/eval/` is an offline rig that measures whether memory actually helps
the tutor, and lets you **tune recall configuration** empirically instead of
guessing. It runs against the core library directly (`Engram.from_env()`) — no
HTTP, no web console — driving a scripted-but-LLM-authored learner through
`ingest → consolidate → recall`.

Design spec: [`docs/superpowers/specs/2026-06-27-engram-phase-5-eval-harness-design.md`](superpowers/specs/2026-06-27-engram-phase-5-eval-harness-design.md).
Usage commands: see README §3.

## The unit of work: a scenario

A scenario ([`eval/scenarios/*.yaml`](../eval/scenarios/)) declares:
- **persona** + **hidden_state** — what the learner has mastered, a misconception,
  a preference, a goal.
- **sessions** — per-session *intents* the LLM student follows.
- **probes** — a query plus the node labels recall *should* surface (and
  `mastered_not_expected` labels that should **not** dominate).

## The flow

```
gen ──> fixture (committed JSON: transcript + frozen graph)
            ├──> sweep  (tuning: recall-probe arm, deterministic)
            └──> demo   (proof:  behavior arm, ON vs baseline, LLM-judged)
```

1. **`gen`** — an LLM *student* (temp-0-intended) converses with the live tutor
   following each session's intent; the events are consolidated into a graph; the
   transcript + graph (nodes **with embeddings**) are frozen into a fixture under
   `eval/fixtures/`. Done once; committed so replays are reproducible. Every run
   uses a throwaway `eval:<scenario>:<runid>` learner that is deleted afterward.

2. **`sweep`** (the tuning loop) — loads the frozen graph and runs each probe
   through `recall()` under every config in a grid, scoring deterministically.

3. **`demo`** (the proof) — replays the learner turns against the live tutor twice:
   **memory ON** (real recall) vs a **naive baseline** (the last-N raw turns), then
   an LLM *judge* grades each reply. Prints the headline comparison.

## The two arms

| | Recall-probe arm (`sweep`) | Behavior arm (`demo`) |
|---|---|---|
| Question | Does recall surface the right nodes? | Does memory change tutor behavior? |
| LLM in loop | Embedder only | Tutor + judge |
| Determinism | Reproducible (frozen graph) | Noisy (LLM) |
| Use | **Tuning signal** | Human-legible headline |

**Recall metrics:** `node_hit_rate`, `full_hit_rate`, `mean_rank`,
`mastered_leak_rate`.
**Behavior metrics:** `re_explanation_rate`, `preference_honored_rate`,
`mean_adapt_score` — reported ON vs baseline.

## Two-tier sweep

Recall scoring is pure Python (`Recall._score`), so weight changes don't require
rebuilding the graph:
- **Tier-1** (cheap, embedder-only): `recall_w_*`, `recall_seed_k`, `recall_hops`,
  `recall_fanout`, `recall_default_budget` — re-score the frozen graph. This is what
  the `sweep` CLI runs.
- **Tier-2** (rebuild from transcript): Keeper/decay params change the graph, so the
  transcript must be re-consolidated per grid point. Use `sweep ... --tier 2` (LLM in
  the loop — costs money with a real provider).

## Modules

| File | Responsibility |
|---|---|
| `scenario.py` | scenario dataclasses + YAML loader |
| `fixtures.py` | snapshot/save/load a graph, id-remap load, one-shot `gen` |
| `arms.py` | recall-probe arm + scoring, behavior arm + baseline |
| `metrics.py` | deterministic aggregation + LLM judge |
| `sweep.py` | grid expansion, Tier-1 runner, Tier-2 rebuild helper |
| `report.py` | markdown table + CSV + headline line |
| `runner.py` | run orchestration: run-scoped Engram, sim clock, sessions → checks |
| `runs.py` | filesystem run store (`eval/runs/<id>/`: run.json, events, snapshots) |
| `checks/` | pluggable checks (one file each) registered via `registry.py` |
| `regression.py` | metric-direction-aware compare of a run vs a baseline |
| `__main__.py` | CLI: `gen` / `sweep` / `demo` / `report` / `run` |

## Current status

The `calc-mastery` scenario runs end-to-end through every verb — `gen`, `sweep`,
`demo`, and the v2 `run` verb (multi-session, sim-clock lifecycle + the check
suite). It is now a **multi-session scenario** (a mastered concept established
early and probed late) rather than the original single-session smoke test, so
recall and behavior have room to discriminate. Regression gating against a
committed baseline is wired via `run --against` (see below).

## Runs, checks & UI (v2)

The `run` verb is the CI-facing entry point. It executes a scenario against the
live core (`Engram.from_env()`) on a **simulated clock**, drives each session
(honoring per-session `gap_days` time gaps so decay/prune math advances), then
applies the scenario's **checks** and writes a full record under
`eval/runs/<scenario>-<id>/` (`run.json`, `events.jsonl`, `transcript.jsonl`,
`snapshots/`). Every run uses a throwaway `eval:<scenario>:run-<id>` learner that
is deleted afterward.

```
python -m engram.eval run <scenario.yaml> \
    [--checks recall_probes,dedup] \   # subset override (default: scenario's checks:)
    [--budget-usd 0.50] \              # hard cost cap (needs prices configured)
    [--against <run-dir-or-id>] \      # regression-gate vs a baseline
    [--tolerance 0.02]                 # slack in the worse direction only
```

It prints a `[PASS]`/`[FAIL]` line per check (with metrics and up to five
`details`), then a `status=… cost=$… dir=…` summary line. **Exit code is 1** if
the run status is not `passed` **or** any regression is found vs `--against`;
otherwise 0.

**The six checks** (each a file in `checks/`, registered by name):

| Check | Measures |
|---|---|
| `recall_probes` | Do the scenario probes surface the expected nodes (`node_hit_rate`, `mean_rank`, `mastered_leak_rate`)? |
| `dedup` | Are near-duplicate concepts merged, not fanned out (`duplicate_label_rate`)? |
| `importance` | Do high-signal nodes rank above noise? |
| `integrity` | Graph well-formedness (`integrity_failures`, `orphan_edges`). |
| `lifecycle` | Do decay/prune transitions fire correctly over sim time (`lifecycle_failures`)? |
| `behavior` | Live arm — does memory change tutor behavior (`on_re_explanation_rate` vs `baseline_re_explanation_rate`)? Spends LLM calls (`needs="live"`). |

**Scenario YAML additions** (both optional, backward-compatible):

```yaml
sessions:
  - intent: "…"
    turns: 3
    gap_days: 14        # advance the sim clock 14 days before this session
checks:
  - recall_probes        # bare name, or…
  - name: dedup
    threshold: 0.1       # …a mapping to pass params to the check
```

**Environment variables:**

- `ENGRAM_EVAL_UI` (bool, default false) — enables the live run console/UI.
- `ENGRAM_EVAL_PRICE_IN_PER_M` / `ENGRAM_EVAL_PRICE_OUT_PER_M` (float USD per 1M
  tokens, default 0.0) — token prices used to meter run cost. `--budget-usd` can
  only trip when these are set; otherwise cost stays $0 and the cap is a no-op
  (the run emits a warning).

**Regression gating (`--against`)** resolves its argument three ways: a `run.json`
path, a run directory, or a run-id suffix matched under `eval/runs/` (including
`eval/runs/baselines/`, which **is** committed while all other runs are
gitignored). An ambiguous suffix errors and lists the matches. Comparison is
**metric-direction-aware**: `regression.py`'s `LOWER_BETTER` set knows that
`mean_rank`, `*_leak_rate`, `*_failures`, `orphan_edges`, `usd`, etc. should go
**down** while hit rates should go **up**; `--tolerance` grants slack only in the
worse direction. Metrics present in only one of the two runs are ignored (a fully
disjoint metric set yields no regressions but prints a warning).

## Known limitations & future improvements

The v2 `run` verb + multi-session scenarios address the early
discrimination/baseline/budget gaps. Use [`eval/scenarios/multi-session-em.yaml`](../eval/scenarios/multi-session-em.yaml)
for the discriminating eval (near-duplicate bait via "EM induction" /
"electromagnetic induction", decay via `gap_days`, and over-merge guards on
Faraday vs Lenz vs induction). The default sweep grid now includes
`recall_default_budget: [150, 400, 800]` so budget pressure is part of tuning.
Tier-2 sweep is wired: `python -m engram.eval sweep <scenario> <fixture> --grid G --tier 2`
(rebuilds the graph per grid point — LLM in the loop, costs money).

**Eval gates** for the memory-quality fixes: run
`python -m engram.eval run eval/scenarios/multi-session-em.yaml` and expect
`dedup` (`duplicate_label_rate <= 0.05`) and `importance`
(`importance_coverage >= 0.9`) to pass alongside the other scenario checks.

**Repair** retroactively merges duplicate nodes on existing graphs:
`python -m engram.eval repair --learner <id>` (CLI) or `POST /admin/repair-merges`
(HTTP admin surface).

Remaining items:

1. **Determinism / sample size.** The behavior arm is a single run over a few
   turns and `temperature` is unset, so judge numbers wobble between runs. *Fix:*
   pin `temperature=0` for student/tutor/judge (deferred — it touches the shared
   LLM adapter and would also change the production tutor) and/or average N runs.

2. **Scenario fidelity / student drift.** The LLM student can wander off the
   seeded hidden state — in the first run the intended "concrete examples"
   preference surfaced as "active quizzing." *Fix:* make session intents
   explicitly voice the preference, or validate the generated fixture against the
   hidden state before committing it.

3. **No query-embedding cache across combos.** Each sweep combo re-embeds the same
   probe queries. Cheap to cache; minor cost today.

4. **Optional third arm.** The spec notes a `mem0` baseline arm as benchmarked
   prior art — not built.
