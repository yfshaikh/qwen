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

**The checks** (each a file in `checks/`, registered by name):

| Check | Measures |
|---|---|
| `recall_probes` | Do the scenario probes surface the expected nodes (`node_hit_rate`, `mean_rank`, `mastered_leak_rate`)? |
| `dedup` | Are near-duplicate concepts merged, not fanned out (`duplicate_label_rate`, per live node)? Legacy generator scenarios only — frozen cases use `concepts`. |
| `importance` | Do high-signal nodes rank above noise? |
| `integrity` | Graph well-formedness (`integrity_failures`, `orphan_edges`). |
| `lifecycle` | Do decay/prune transitions fire correctly over sim time (`lifecycle_failures`)? |
| `behavior` | Live arm — does memory change tutor behavior (`on_re_explanation_rate` vs `baseline_re_explanation_rate`)? Spends LLM calls (`needs="live"`). |
| `concepts` | Required concepts present (via calibrated aliases), absolute duplicate caps, cross-type duplicate detection. |
| `edges` | Expected prerequisite/part_of edges present with the right direction; reversals forbidden. |
| `abstention` | No hallucinated concepts — labels the transcript never justified. |
| `knowledge_update` | Misconception → correction arcs land in mastery/evidence. |
| `preferences` | Durable preferences/goals extracted without over-extraction; transient requests are not minted as preferences. |

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

## Frozen benchmarks & regression testing

Two hand-authored, frozen scenarios are the trustworthy core of the eval:
[`em-frozen-v1.yaml`](../eval/scenarios/em-frozen-v1.yaml) (the iteration case)
and [`sat-linear-holdout-v1.yaml`](../eval/scenarios/sat-linear-holdout-v1.yaml)
(the overfitting guard — **never** point an iterate-verify loop at it; it exists
to distinguish "Engram improved" from "Engram memorised em-frozen-v1"). Both
freeze student **and** tutor text, so the extractor is the only LLM in the loop
and a graph difference means the Keeper changed.

### The verdicts are not deterministic — use `--repeat`

A frozen transcript pins the eval's *input*, not its *verdict*: at
temperature 0 on byte-identical sessions, the extractor still varies
run-to-run. Measured 2026-07-18 on post-§3.1 code (×10, all scored,
[`eval/runs/variance-em-frozen-v1.md`](../eval/runs/variance-em-frozen-v1.md)):

| check | verdict stability (n=10) | single run trustworthy? |
|---|---|---|
| `abstention`, `concepts`, `integrity`, `recall_probes` | 10/10 pass | yes |
| `preferences` | 9/10 | mostly — one flip in ten |
| `knowledge_update` | 7/10 | **no** — use `--repeat` |
| `edges` | 4/10 | **no** — ~50% flip rate; even majority-of-5 is coin-flippy. Raise N or treat as advisory until edge extraction stabilizes further |

(For contrast, before the §3.1 fixes — 2026-07-17, n=7 — `concepts` and
`knowledge_update` were stably RED and `edges` passed 1/7. The fixes moved the
distributions, not just the verdicts.)

A "stable" verdict at n runs only resolves flip rates ≥ ~1/n — `edges` looked
stably red at n=4 and flips at n=7. Re-measure with
`python tools/eval_variance.py <scenario> -n 10` after any change to the
extraction pipeline; stability claims go stale when the code under test moves
(this table has already been rewritten once for exactly that reason).

### Regression protocol for new features

```
python -m engram.eval run eval/scenarios/em-frozen-v1.yaml --repeat 5 --concurrency 1
```

- Per-check verdict is a **strict majority of the asked N**; runs lost to 429s
  or crashes count against (a gate must not pass on a sample it didn't get).
  Flaky checks are flagged in the output. Exit 0 iff every check holds a
  majority.
- **Compare aggregates to aggregates.** Run `--repeat` before the feature and
  after; compare per-check pass counts and metric means. Never compare single
  run to single run — that is how a coin flip becomes a "verified fix".
- Power: N=5 catches gross regressions (stable-pass → mostly-fail), not subtle
  pass-rate drops. Runs cost ~$0.005; raise N when the answer matters.
- `--concurrency 1` on Groq's free tier — its 8k TPM cap loses ~3/10 runs at
  concurrency 2 even with the adapter's retries. For its 200k tokens/DAY cap
  (which no backoff outlives), set `CEREBRAS_API_KEY`: the LLM adapter falls
  back to Cerebras on a 429 that survives retries — fallback ONLY, never
  load-balanced, model name's vendor prefix stripped. ⚠️ A fallback-served run
  is a different provider serving the same model: label phrasings measurably
  shift, so don't recalibrate aliases from fallback runs alone.
- `--against` (metric-level regression vs a baseline run) does not compose with
  `--repeat` yet; cross-aggregate metric comparison is manual.

### What this instrument cannot tell you

- Both scenarios are **synthetic authored prose**. Engram has never been
  evaluated on a real learner conversation; claims transfer only as far as the
  transcripts resemble one.
- Checks match concepts via **aliases calibrated to the current extractor's
  labels**, plus an **LLM residue matcher** (2026-07-18; built after measuring
  that session-0 label minting drifts run-to-run and provider-to-provider even
  at temperature 0, so no authored alias list converges). Deterministic alias
  matching runs first; ONE `judge`-role call maps only the leftover
  (missing-expected × unmatched-graph-labels). The LLM decides label IDENTITY
  only — counts, duplicate caps, edge direction, and mastery assertions stay
  deterministic on top, and two labels mapping to one concept still fails as a
  duplicate. Every LLM-decided pair is printed in the check details
  (`llm-matched 'X' -> 'Y'`) for human audit; matcher failure degrades to plain
  deterministic matching. It is deliberately conservative: genuinely arguable
  identities (e.g. 'single linear equations' vs 'Solving linear equations' —
  the objects vs the skill) are declined and stay visible in the
  `unmatched labels` line for a human to judge. Do not "fix" those by editing
  the fixture unilaterally; ground-truth changes remain a human decision.
- The frozen path exercises **ingest → consolidate only**. Recall weights and
  tutor behavior are covered by `sweep`/`demo`/`behavior`, which are noisier.

### Ground truth is read-only to automation

The frozen fixtures and every check module are digest-pinned by
`tests/eval/test_benchmark_integrity.py` — any edit fails the suite loudly.
Agents iterating on Engram change Engram, not the referee: widening a
threshold or adding an alias makes the number green while the bug ships.
Deliberate ground-truth changes (recalibration, new checks) are a human
decision, finalized by repinning the digest.

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

1. **Determinism / sample size.** ~~Pin temperature~~ — done per role
   (`Settings.temperature_for`; extractor/reflector at 0), and measured to be
   insufficient: temp 0 does **not** deliver stable verdicts (see "Frozen
   benchmarks" above). N-run aggregation (`run --repeat`) is the working answer.

2. **Scenario fidelity / student drift.** The LLM student can wander off the
   seeded hidden state — in the first run the intended "concrete examples"
   preference surfaced as "active quizzing." *Fix:* make session intents
   explicitly voice the preference, or validate the generated fixture against the
   hidden state before committing it.

3. **No query-embedding cache across combos.** Each sweep combo re-embeds the same
   probe queries. Cheap to cache; minor cost today.

4. **Optional third arm.** The spec notes a `mem0` baseline arm as benchmarked
   prior art — not built.
