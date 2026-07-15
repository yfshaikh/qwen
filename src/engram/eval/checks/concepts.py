"""`concepts` — are the expected concepts present, and exactly once?

Reads `scenario.expect.concepts` (ground truth) and `scenario.expect.no_duplicates`.

Supersedes `dedup` for frozen benchmarks. `dedup` reports a rate over C(n,2) pairs,
so its denominator grows quadratically: at 28 nodes that is 378 pairs, and the 0.05
threshold tolerates 18 duplicate pairs. It has never been shown to fail on a real
duplicate. This check counts duplicates absolutely.
"""
from __future__ import annotations

from collections import defaultdict

from engram.core.text import normalize_label
from engram.eval.checks._match import live_nodes, resolve, snapshot_nodes
from engram.eval.registry import CheckResult, EvalContext, check


@check("concepts")
async def concepts(ctx: EvalContext) -> CheckResult:
    expect = getattr(ctx.scenario, "expect", {}) or {}
    spec = expect.get("concepts") or []
    required = [str(c["label"]) for c in spec if isinstance(c, dict) and c.get("label")]
    aliases = getattr(ctx.scenario, "aliases", None)

    nodes = snapshot_nodes(ctx)
    res = resolve(nodes, required, aliases, node_type="concept")
    failures: list[str] = []

    for label in res.missing():
        failures.append(f"missing concept {label!r}")

    # >1 match is a duplicate: identity is equality against authored aliases, so a
    # match is a match. The blind spot is the other way — a variant nobody authored
    # an alias for is invisible here (see test_concepts_blind_to_unaliased_variant).
    # max_concepts below is what covers that, since a count cannot be relabelled.
    for label, dupes in res.duplicated().items():
        failures.append(f"concept {label!r} matched {len(dupes)} live nodes: {dupes}")

    # Alias-proof over-extraction gate. Fragmentation ('Flux', 'Flux with angles',
    # 'EMF from flux change' as three nodes) is the bug this benchmark exists for,
    # and no identity check catches it — every fragment is a legitimate label. The
    # cap is deliberately generous: the extras ARE in the transcript, just too
    # granular, so this asserts proportion, not a curriculum.
    cap = expect.get("max_concepts")
    live_concepts = live_nodes(nodes, "concept")
    if cap is not None and len(live_concepts) > int(cap):
        failures.append(
            f"over-extraction: {len(live_concepts)} live concepts, max {cap} "
            f"({len(required)} expected) — {sorted(str(n.get('label')) for n in live_concepts)}")

    dup_pairs = 0
    cross_type = 0
    if expect.get("no_duplicates"):
        # Deliberately lexical-only. A cosine pass would need a threshold, and
        # thresholds are the thing this benchmark exists to stop trusting. Two
        # concepts sharing a normalized label are duplicates by inspection; two
        # that merely embed closely are a judgement call, not a gate.
        by_norm: dict[str, list[str]] = defaultdict(list)
        for n in live_nodes(nodes, "concept"):
            norm = normalize_label(str(n.get("label", "")))
            if norm:
                by_norm[norm].append(str(n.get("label")))
        for norm, labels in sorted(by_norm.items()):
            if len(labels) > 1:
                dup_pairs += 1
                failures.append(f"duplicate concepts share normalized label {norm!r}: {labels}")

        # CROSS-TYPE duplicates. `_resolve` starts every comparison with
        # `if w.node.type != cand_type: continue` — it NEVER merges across
        # NodeType. So a concept the extractor mis-types as a goal becomes a
        # phantom that no dedup layer can ever reach, at any threshold.
        #
        # Not hypothetical, and not inert: on run a2b4c404 the graph held BOTH
        # `[conc] "Faraday's law"` and `[goal] "Faraday's law"` (same for
        # 'transformers'), and the goal-typed phantoms carried 4 of the 9 edges —
        # including a backwards `transformers[goal] --prerequisite--> EM induction`.
        # Scoped to no_duplicates because that is exactly what this is: a duplicate
        # the type filter hides.
        by_type: dict[str, set[str]] = defaultdict(set)
        for n in live_nodes(nodes):  # NB: every type, not just concepts
            norm = normalize_label(str(n.get("label", "")))
            if norm:
                by_type[norm].add(str(n.get("type")))
        for norm, types in sorted(by_type.items()):
            if len(types) > 1:
                cross_type += 1
                failures.append(
                    f"{norm!r} exists under multiple node types {sorted(types)}: "
                    "_resolve never merges across type, so this can never dedup")

    if failures:
        failures.append(res.unmatched_note())

    live_count = len(live_nodes(nodes, "concept"))
    return CheckResult(
        name="concepts",
        metrics={"concepts_expected": float(len(required)),
                 "concepts_missing": float(len(res.missing())),
                 "concepts_duplicated": float(len(res.duplicated())),
                 "duplicate_label_groups": float(dup_pairs),
                 "cross_type_duplicates": float(cross_type),
                 "live_concepts": float(live_count)},
        passed=not failures, details=failures)
