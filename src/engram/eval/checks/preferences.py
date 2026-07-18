"""`preferences` — did the graph learn the learner's standing preferences and
goals, and did it resist minting a node for every passing remark?

Reads `scenario.expect.preferences.{required,forbidden,max}` and
`scenario.expect.goals.{required,forbidden,max}`.

WHY PREFERENCES AND GOALS SHARE A CHECK
They are the same kind of thing and fail the same way: both are free-form,
learner-authored, never in any curriculum, and both are governed by
`filter_provenance` (which drops pref/goal candidates traced only to tutor
speech). Concepts are the opposite — they come from a syllabus and can be
classified. Splitting these two apart would mean two files asserting the same
property with the same helper.

THE `forbidden` LIST IS THE POINT
`_resolve` has no reject path: every candidate returns either an existing id
(merge) or None (create). Engram cannot decline a candidate, which is why real
graphs have carried `Monster Problems`, `No Panic Needed`, `Think Like a
Physicist`, and `Confidence-boosting motivation` as learner *preferences*.

`filter_provenance` does not help — the learner genuinely said "give me a monster
problem". It IS their own words; it just isn't a preference. The defect is that
the extractor cannot tell a DURABLE preference ("I prefer bullet points", restated
every session) from a TRANSIENT request ("give me a hard one", said once).

Note this is a QUALITY judgement, not a similarity one — which is why an
`_resolve`-level NOOP would not fix it either. A transient request has no similar
existing node, so cosine is low, so it never enters the reflector band and is
created unopposed. The fix lives in the extraction prompt, not the merge ladder.
"""
from __future__ import annotations

from engram.eval.checks._match import (
    live_nodes,
    mentions_topic,
    resolve_llm,
    snapshot_nodes,
)
from engram.eval.registry import CheckResult, EvalContext, check


def _required(expect: dict, key: str) -> list[str]:
    spec = expect.get(key) or {}
    if isinstance(spec, list):  # bare list shorthand
        return [str(x) for x in spec]
    return [str(x) for x in (spec.get("required") or [])]


def _forbidden(expect: dict, key: str) -> list[str]:
    spec = expect.get(key) or {}
    return [str(x) for x in (spec.get("forbidden") or [])] if isinstance(spec, dict) else []


@check("preferences")
async def preferences(ctx: EvalContext) -> CheckResult:
    expect = getattr(ctx.scenario, "expect", {}) or {}
    aliases = getattr(ctx.scenario, "aliases", None)
    nodes = snapshot_nodes(ctx)
    failures: list[str] = []
    notes: list[str] = []

    for key, node_type in (("preferences", "preference"), ("goals", "goal")):
        want = _required(expect, key)
        res, llm_notes = await resolve_llm(ctx, nodes, want, aliases,
                                           node_type=node_type)
        notes.extend(llm_notes)
        for label in res.missing():
            failures.append(f"missing {node_type} {label!r}; {res.unmatched_note()}")
        for label, dupes in res.duplicated().items():
            failures.append(f"{node_type} {label!r} matched {len(dupes)} nodes: {dupes}")

        # Containment, like abstention: "must not appear" is a different question
        # from "which node is this?". A transient request minted as a preference is
        # still minted when it arrives as 'Monster problems, please' — identity
        # matching would wave through every variant of the thing we're forbidding,
        # and the extractor's variants are exactly what we cannot predict.
        for label in _forbidden(expect, key):
            hits = mentions_topic(live_nodes(nodes, node_type), label)
            if hits:
                failures.append(
                    f"transient request minted as a {node_type}: {label!r} matched "
                    f"{[str(n.get('label')) for n in hits]}")

    # The count assertion. `forbidden` can only name spurious labels someone already
    # saw; across 5 identical runs the extractor invented a DIFFERENT set each time
    # ('Learn Faraday's law', 'midterm preparation', "master Lenz's law direction"),
    # so enumeration can never catch up. A count needs no prediction, and unlike
    # identity matching it cannot be dodged by relabelling — which is what makes it
    # the honest gate for an agent's fix-loop.
    for key, node_type in (("preferences", "preference"), ("goals", "goal")):
        spec = expect.get(key)
        cap = spec.get("max") if isinstance(spec, dict) else None
        if cap is None:
            continue
        got = live_nodes(nodes, node_type)
        if len(got) > int(cap):
            failures.append(
                f"over-extraction: {len(got)} live {node_type} nodes, max {cap} — "
                f"{sorted(str(n.get('label')) for n in got)}")

    n_pref = len(live_nodes(nodes, "preference"))
    n_goal = len(live_nodes(nodes, "goal"))
    return CheckResult(
        name="preferences",
        metrics={"live_preferences": float(n_pref),
                 "live_goals": float(n_goal),
                 "preference_failures": float(len(failures))},
        passed=not failures, details=failures + notes)
