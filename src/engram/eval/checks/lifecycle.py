from __future__ import annotations

from engram.eval.registry import CheckResult, EvalContext, check
from engram.eval.scenario import alias_forms


def _matches(nodes: list[dict], label: str,
             aliases: dict[str, list[str]] | None = None) -> list[dict]:
    needles = [f.lower() for f in alias_forms(label, aliases)]
    return [n for n in nodes
            if any(needle in n["label"].lower() for needle in needles)]


def _find(nodes: list[dict], label: str,
          aliases: dict[str, list[str]] | None = None) -> dict | None:
    """A representative node for the concept: a LIVE match if one exists, else
    the first match. With aliases a concept can appear as both a forgotten
    (old-label) node and a live (canonical-label) node — a live match means the
    concept is retained, so prefer it."""
    matches = _matches(nodes, label, aliases)
    return next((n for n in matches if not n.get("forgotten_at")), matches[0] if matches else None)


@check("lifecycle")
async def lifecycle(ctx: EvalContext) -> CheckResult:
    expect = ctx.param("expect", {}) or {}
    aliases = getattr(ctx.scenario, "aliases", None)
    first = ctx.snapshots[0]["graph"]["nodes"] if ctx.snapshots else []
    last = ctx.snapshots[-1]["graph"]["nodes"] if ctx.snapshots else []
    failures: list[str] = []
    checked = 0

    for label in expect.get("forgotten", []):
        checked += 1
        matches = _matches(last, label, aliases)
        live = next((n for n in matches if not n.get("forgotten_at")), None)
        if not matches:
            failures.append(f"forgotten {label!r}: never existed in final snapshot")
        elif live is not None:  # a live variant means the concept isn't forgotten
            failures.append(f"forgotten {label!r}: still live (salience={live.get('salience')})")

    for label in expect.get("kept", []):
        checked += 1
        matches = _matches(last, label, aliases)
        if not any(not n.get("forgotten_at") for n in matches):
            failures.append(f"kept {label!r}: missing or forgotten")

    for label in expect.get("decayed", []):
        checked += 1
        a, b = _find(first, label, aliases), _find(last, label, aliases)
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
