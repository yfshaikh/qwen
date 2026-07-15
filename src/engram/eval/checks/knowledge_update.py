"""`knowledge_update` — do mastery arcs track what actually happened?

Reads `scenario.expect.mastery`, a list of assertions against a snapshot:

    - concept: Ohm's law
      after_session: 0
      min: 0.6                      # demonstrated correctly, never re-taught
    - concept: Lenz's law
      after_session: 1
      max: 0.5                      # misconception held
    - concept: Lenz's law
      after_session: 2
      increased_from_session: 1     # <- the correction landed

THE GAP THIS FILLS
`knowledge updates` is a LongMemEval ability (facts that change over time) with no
coverage here. Worse: multi-session-em.yaml is BUILT around a misconception the
tutor is supposed to correct across three sessions ("induced current opposes motion
because energy is lost as heat"), and nothing ever asserted the correction reaches
the graph. The scenario's whole reason for existing was unmeasured, and the
Keeper's `resolve_contradiction` path appears unexercised.

`increased_from_session` is the misconception-correction assertion: it is a
relative comparison, not an absolute floor, because what matters pedagogically is
that the graph MOVED when the learner's understanding moved. Pinning an absolute
value would encode a guess about the EWMA's exact arithmetic.
"""
from __future__ import annotations

from typing import Any

from engram.eval.checks._match import resolve, snapshot_nodes
from engram.eval.registry import CheckResult, EvalContext, check


def _mastery_of(ctx: EvalContext, concept: str, session: int,
                aliases: Any) -> tuple[float | None, str | None]:
    """(mastery, error). A missing node or a null mastery is an ERROR, never a
    pass. Coercing None to 0.0 would let a data bug report as a satisfied
    expectation — the same trap lifecycle.py documents for salience."""
    nodes = snapshot_nodes(ctx, session)
    if not nodes:
        return None, f"no snapshot for session {session}"
    res = resolve(nodes, [concept], aliases, node_type="concept")
    got = res.by_label.get(concept) or []
    if not got:
        return None, f"concept {concept!r} absent after session {session}; {res.unmatched_note()}"
    if len(got) > 1:
        return None, (f"concept {concept!r} ambiguous after session {session}: "
                      f"{[str(n.get('label')) for n in got]}")
    m = got[0].get("mastery")
    if m is None:
        return None, (f"concept {concept!r} has mastery=None after session {session} "
                      "(data bug, not a pass)")
    return float(m), None


@check("knowledge_update")
async def knowledge_update(ctx: EvalContext) -> CheckResult:
    expect = getattr(ctx.scenario, "expect", {}) or {}
    specs = [s for s in (expect.get("mastery") or []) if isinstance(s, dict)]
    aliases = getattr(ctx.scenario, "aliases", None)

    failures: list[str] = []
    checked = 0

    for spec in specs:
        concept = str(spec.get("concept", ""))
        if not concept or "after_session" not in spec:
            failures.append(f"malformed mastery expectation: {spec!r}")
            continue
        session = int(spec["after_session"])
        checked += 1

        m, err = _mastery_of(ctx, concept, session, aliases)
        if err is not None:
            failures.append(err)
            continue
        assert m is not None  # err is None => m is set

        if "min" in spec and m < float(spec["min"]):
            failures.append(
                f"{concept!r} mastery {m:.3f} after s{session} is below min {spec['min']}")
        if "max" in spec and m > float(spec["max"]):
            failures.append(
                f"{concept!r} mastery {m:.3f} after s{session} is above max {spec['max']}")

        if "increased_from_session" in spec:
            prior_session = int(spec["increased_from_session"])
            prior, perr = _mastery_of(ctx, concept, prior_session, aliases)
            if perr is not None:
                failures.append(f"cannot compare {concept!r} to s{prior_session}: {perr}")
            elif prior is not None and not (m > prior):
                failures.append(
                    f"{concept!r} mastery did not increase s{prior_session} -> s{session}: "
                    f"{prior:.3f} -> {m:.3f} (the correction never reached the graph)")

    return CheckResult(
        name="knowledge_update",
        metrics={"mastery_expectations": float(checked),
                 "mastery_failures": float(len(failures))},
        passed=not failures, details=failures)
