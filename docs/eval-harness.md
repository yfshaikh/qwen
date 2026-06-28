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
  transcript must be re-consolidated per grid point. Implemented as the
  `rebuild_graph_from_transcript` helper but **not yet wired into the CLI** (see
  Future improvements).

## Modules

| File | Responsibility |
|---|---|
| `scenario.py` | scenario dataclasses + YAML loader |
| `fixtures.py` | snapshot/save/load a graph, id-remap load, one-shot `gen` |
| `arms.py` | recall-probe arm + scoring, behavior arm + baseline |
| `metrics.py` | deterministic aggregation + LLM judge |
| `sweep.py` | grid expansion, Tier-1 runner, Tier-2 rebuild helper |
| `report.py` | markdown table + CSV + headline line |
| `__main__.py` | CLI: `gen` / `sweep` / `demo` / `report` |

## Current status

The `calc-mastery` scenario is a **working smoke test**: `gen`, `sweep`, and `demo`
all run end-to-end and produce sensible output. It is **not yet a discriminating
tuning scenario** — see below.

## Known limitations & future improvements

Observed from the first real runs (4-node graph, ~5-turn replay):

1. **Scenarios too small to discriminate.** On a 4-node graph every sweep config
   tied at `node_hit_rate=1.0` — `seed_k`/`hops`/weights can't change which nodes
   come back when there are so few. *Fix:* longer, multi-session scenarios that
   build 15–30 nodes so recall must make choices.

2. **The baseline only loses when facts scroll out of its window.** The naive
   baseline is "the last-N raw turns" (N=10). On a short replay it contains the
   whole conversation, so memory shows no `re_explanation_rate` gain. *Fix:*
   multi-session arcs where a mastered concept / preference is established **early**
   (beyond the last-N window) and probed **late** — the case the spec describes
   ("session 3 must not re-explain what was mastered in session 1").

3. **Tight recall budget for a real ranking signal.** With no budget pressure
   everything fits, so `mean_rank` ordering never affects which nodes appear.
   *Fix:* sweep `recall_default_budget` low (e.g. `[150, 400]`).

4. **Determinism / sample size.** The behavior arm is a single run over a few
   turns and `temperature` is unset, so judge numbers wobble between runs. *Fix:*
   pin `temperature=0` for student/tutor/judge (deferred — it touches the shared
   LLM adapter and would also change the production tutor) and/or average N runs.

5. **Scenario fidelity / student drift.** The LLM student can wander off the
   seeded hidden state — in the first run the intended "concrete examples"
   preference surfaced as "active quizzing." *Fix:* make session intents
   explicitly voice the preference, or validate the generated fixture against the
   hidden state before committing it.

6. **Tier-2 sweep not exposed.** `rebuild_graph_from_transcript` exists but the CLI
   only runs Tier-1. *Fix:* add a `--tier 2` path to the `sweep` command.

7. **No query-embedding cache across combos.** Each sweep combo re-embeds the same
   probe queries. Cheap to cache; minor cost today.

8. **Optional third arm.** The spec notes a `mem0` baseline arm as benchmarked
   prior art — not built.
