"""`preferences` — did the graph learn the learner's standing preferences and
goals, and did it resist minting a node for every passing remark?

Reads `scenario.expect.preferences.{required,forbidden}` and
`scenario.expect.goals.required`.

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

from engram.eval.checks._match import live_nodes, match_concept, resolve, snapshot_nodes
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

    for key, node_type in (("preferences", "preference"), ("goals", "goal")):
        want = _required(expect, key)
        res = resolve(nodes, want, aliases, node_type=node_type)
        for label in res.missing():
            failures.append(f"missing {node_type} {label!r}; {res.unmatched_note()}")
        for label, dupes in res.duplicated().items():
            failures.append(f"{node_type} {label!r} matched {len(dupes)} nodes: {dupes}")

        # Aliases deliberately NOT applied to forbidden targets: these are literal
        # labels that must not appear, and broadening them via the alias map would
        # fail nodes that merely resemble one.
        for label in _forbidden(expect, key):
            hits = match_concept(live_nodes(nodes, node_type), label, None)
            if hits:
                failures.append(
                    f"transient request minted as a {node_type}: {label!r} matched "
                    f"{[str(n.get('label')) for n in hits]}")

    n_pref = len(live_nodes(nodes, "preference"))
    n_goal = len(live_nodes(nodes, "goal"))
    return CheckResult(
        name="preferences",
        metrics={"live_preferences": float(n_pref),
                 "live_goals": float(n_goal),
                 "preference_failures": float(len(failures))},
        passed=not failures, details=failures)
