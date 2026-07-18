"""`edges` — do the graph's relations match the authored curriculum?

Reads `scenario.expect.edges.required` and `.forbidden`, each a list of
`[source_label, target_label, type]`.

THE GAP THIS FILLS
`integrity` is the only other check that touches edges, and it only finds orphans
(edges pointing at absent node ids) — referential, not semantic. It cannot tell
`A --prerequisite--> B` from `B --prerequisite--> A`. Nothing else asserts a single
relation. So relation accuracy has been whatever the extractor said, unvalidated:
a spot-check of run edb608f6 found `Leakage inductance --prerequisite--> Inductive
reactance` and `LC energy and phase --prerequisite--> Energy conservation`, both
backwards.

`forbidden` exists specifically to catch DIRECTION CHURN: keeper.py:191 adopts the
proposal's direction when upgrading an edge, so a later wrong-direction proposal
silently flips a settled edge. A `required` check alone would pass while both
directions sat in the graph.

Extra edges are NOT failed — only missing `required` and present `forbidden`. The
authored ground truth is deliberately small (only relations two independent
derivations agreed on); failing everything outside it would fail correct physics.
"""
from __future__ import annotations

from typing import Any

from engram.eval.checks._match import node_id_set, resolve_llm, snapshot_nodes
from engram.eval.registry import CheckResult, EvalContext, check


def _triples(raw: Any) -> list[tuple[str, str, str]]:
    out = []
    for e in raw or []:
        if isinstance(e, (list, tuple)) and len(e) == 3:
            out.append((str(e[0]), str(e[1]), str(e[2])))
    return out


def _snapshot_edges(ctx: EvalContext) -> list[dict]:
    snaps = ctx.snapshots or []
    if not snaps:
        return []
    try:
        return list(snaps[-1]["graph"]["edges"])
    except (KeyError, TypeError):
        return []


def _present(graph_edges: list[dict], src_ids: set[str], tgt_ids: set[str],
             etype: str) -> bool:
    """Directed: source must be in src_ids and target in tgt_ids. Never symmetric —
    direction is the entire point of this check."""
    return any(str(e.get("source")) in src_ids
               and str(e.get("target")) in tgt_ids
               and str(e.get("type")) == etype
               for e in graph_edges)


@check("edges")
async def edges(ctx: EvalContext) -> CheckResult:
    expect = getattr(ctx.scenario, "expect", {}) or {}
    spec = expect.get("edges") or {}
    required = _triples(spec.get("required"))
    forbidden = _triples(spec.get("forbidden"))
    aliases = getattr(ctx.scenario, "aliases", None)

    nodes = snapshot_nodes(ctx)
    graph_edges = _snapshot_edges(ctx)
    endpoints = {lbl for s, t, _ in required + forbidden for lbl in (s, t)}
    # Resolve against EVERY expected concept, not just the edge endpoints. Scoping
    # it to endpoints made the unmatched note lie: run b060e838 reported "Ohm's law"
    # and "Lenz's law (minus sign)" as unmatched purely because no expected edge
    # names them — they are perfectly good concepts. A diagnostic whose whole job is
    # separating "real bug" from "stale alias" must not itself cry wolf.
    expected_concepts = {str(c["label"]) for c in (expect.get("concepts") or [])
                         if isinstance(c, dict) and c.get("label")}
    res, llm_notes = await resolve_llm(ctx, nodes,
                                       sorted(endpoints | expected_concepts),
                                       aliases, node_type="concept")

    failures: list[str] = []
    checked = 0

    for src, tgt, etype in required:
        checked += 1
        src_nodes, tgt_nodes = res.by_label.get(src) or [], res.by_label.get(tgt) or []
        if not src_nodes or not tgt_nodes:
            # Report the concept gap, not a phantom edge failure. An agent reading
            # "missing edge" would go hunting in the Keeper's edge code when the
            # real problem is upstream (or a stale alias).
            absent = [x for x, got in ((src, src_nodes), (tgt, tgt_nodes)) if not got]
            failures.append(
                f"cannot check {src!r} --{etype}--> {tgt!r}: concept(s) absent: {absent}")
            continue
        if not _present(graph_edges, node_id_set(src_nodes), node_id_set(tgt_nodes), etype):
            failures.append(f"missing {src!r} --{etype}--> {tgt!r}")

    for src, tgt, etype in forbidden:
        checked += 1
        src_nodes, tgt_nodes = res.by_label.get(src) or [], res.by_label.get(tgt) or []
        if not src_nodes or not tgt_nodes:
            continue  # concept absent -> the forbidden edge cannot exist. Not a failure.
        if _present(graph_edges, node_id_set(src_nodes), node_id_set(tgt_nodes), etype):
            failures.append(
                f"FORBIDDEN edge present (reversed direction): {src!r} --{etype}--> {tgt!r}")

    if failures:
        failures.append(res.unmatched_note())

    return CheckResult(
        name="edges",
        metrics={"edges_expected": float(len(required)),
                 "edges_checked": float(checked),
                 "edge_failures": float(len([f for f in failures if not f.startswith("unmatched")])),
                 "graph_edges": float(len(graph_edges))},
        passed=not failures, details=failures + llm_notes)
