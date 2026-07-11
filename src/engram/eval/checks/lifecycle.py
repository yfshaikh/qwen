from __future__ import annotations

from engram.eval.registry import CheckResult, EvalContext, check


def _find(nodes: list[dict], label: str) -> dict | None:
    needle = label.lower()
    for n in nodes:
        if needle in n["label"].lower():
            return n
    return None


@check("lifecycle")
async def lifecycle(ctx: EvalContext) -> CheckResult:
    expect = ctx.param("expect", {}) or {}
    first = ctx.snapshots[0]["graph"]["nodes"] if ctx.snapshots else []
    last = ctx.snapshots[-1]["graph"]["nodes"] if ctx.snapshots else []
    failures: list[str] = []
    checked = 0

    for label in expect.get("forgotten", []):
        checked += 1
        n = _find(last, label)
        if n is None:
            failures.append(f"forgotten {label!r}: never existed in final snapshot")
        elif not n.get("forgotten_at"):
            failures.append(f"forgotten {label!r}: still live (salience={n.get('salience')})")

    for label in expect.get("kept", []):
        checked += 1
        n = _find(last, label)
        if n is None or n.get("forgotten_at"):
            failures.append(f"kept {label!r}: missing or forgotten")

    for label in expect.get("decayed", []):
        checked += 1
        a, b = _find(first, label), _find(last, label)
        if a is None or b is None:
            failures.append(f"decayed {label!r}: not present in both snapshots")
        elif a.get("salience") is None or b.get("salience") is None:
            # A missing salience is a data bug, not decay — coercing None to 0.0
            # would report it as a (false) pass.
            failures.append(
                f"decayed {label!r}: salience missing "
                f"(first={a.get('salience')}, last={b.get('salience')})")
        elif not (b["salience"] < a["salience"]):
            failures.append(
                f"decayed {label!r}: salience {a['salience']} -> {b['salience']} did not decrease")

    return CheckResult(
        name="lifecycle",
        metrics={"lifecycle_expectations": float(checked),
                 "lifecycle_failures": float(len(failures))},
        passed=not failures, details=failures)
