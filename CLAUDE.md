# Engram — agent instructions

## The eval benchmark is read-only

Do not edit `eval/scenarios/em-frozen-v1.yaml`, `eval/scenarios/sat-linear-holdout-v1.yaml`,
or anything under `src/engram/eval/checks/`. They are the referee: digest-pinned
by `tests/eval/test_benchmark_integrity.py`, which fails loudly on any edit.
If a check fails, fix the code under test — never widen a threshold, add an
alias, or relax an expectation to go green. Ground-truth changes (recalibration,
new checks) are a human decision, finalized by repinning the digest.

Never point an iterate-verify loop at `sat-linear-holdout-v1` — it is the
held-out overfitting guard.

## Regression testing

Eval verdicts are NOT deterministic even at temperature 0 on byte-identical
input (measured ×10 on 2026-07-18: `edges` passes 4/10, `knowledge_update`
7/10, `preferences` 9/10; the other four checks 10/10). To verify a fix or
check for regressions:

```
python -m engram.eval run eval/scenarios/em-frozen-v1.yaml --repeat 5 --concurrency 1
```

Compare aggregates to aggregates (before-N-runs vs after-N-runs), never single
run to single run. A single lucky pass is not a verified fix. Full protocol and
current per-check trustworthiness: `docs/eval-harness.md` § "Frozen benchmarks
& regression testing".
