"""`abstention` — did the extractor invent curriculum that was never discussed?

Reads `scenario.expect.abstention`: concept labels that appear NOWHERE in the
transcript and therefore must not exist in the graph.

WHY THIS MATTERS MORE THAN A MISSING CONCEPT
For a tutor, confidently telling a student "you're weak on Lenz's law" about
something they never studied is WORSE than forgetting — a gap is recoverable, a
confident fabrication destroys trust in the memory entirely. Nothing checked this.
It is one of the five LongMemEval abilities (abstention: knowing when not to
answer) and one of the two with no coverage at all.

With a FROZEN transcript the student cannot drift, so the input is fixed by
construction. Any label here appearing in the graph means the EXTRACTOR
hallucinated it from its own weights. That makes this the regression guard for the
whole drift class: every default target in em-frozen-v1 was produced by the
degenerate live run edb608f6 on a scenario whose intents never mentioned it.

Aliases are deliberately NOT applied. These are literal targets — broadening them
via the alias map would fail concepts that merely resemble a forbidden label.
Substring matching still applies, so "AC Circuits" catches "AC Circuits (RLC
Impedance)", which is the intent.
"""
from __future__ import annotations

from engram.eval.checks._match import live_nodes, mentions_topic, snapshot_nodes
from engram.eval.registry import CheckResult, EvalContext, check


@check("abstention")
async def abstention(ctx: EvalContext) -> CheckResult:
    expect = getattr(ctx.scenario, "expect", {}) or {}
    targets = [str(x) for x in (expect.get("abstention") or [])]

    nodes = snapshot_nodes(ctx)
    # Deliberately over ALL nodes, not just live ones: a hallucinated concept that
    # was invented and then decayed away still means the extractor invented it. The
    # graph forgetting the fabrication doesn't make the fabrication acceptable.
    hay = nodes
    failures: list[str] = []

    for target in targets:
        # Containment, not identity: see mentions_topic. A fabrication wearing a
        # qualifier ('AC Circuits (RLC Impedance)') is still the fabrication.
        hits = mentions_topic(hay, target)
        if hits:
            found = [f"{n.get('label')!r}"
                     f"{' (forgotten)' if n.get('forgotten_at') else ''}" for n in hits]
            failures.append(f"hallucinated {target!r}: never in the transcript, found {found}")

    return CheckResult(
        name="abstention",
        metrics={"abstention_targets": float(len(targets)),
                 "hallucinated_concepts": float(len(failures)),
                 "live_nodes": float(len(live_nodes(nodes)))},
        passed=not failures, details=failures)
