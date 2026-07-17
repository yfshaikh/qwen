from __future__ import annotations

from itertools import combinations

from engram.core.recall import cosine_similarity
from engram.core.text import normalize_label
from engram.eval.registry import CheckResult, EvalContext, check

_COSINE_DUP = 0.92


@check("dedup")
async def dedup(ctx: EvalContext) -> CheckResult:
    nodes = [n for n in ctx.snapshots[-1]["graph"]["nodes"] if not n.get("forgotten_at")]
    pairs = list(combinations(nodes, 2))
    dups: list[str] = []
    for a, b in pairs:
        lexical = normalize_label(a["label"]) == normalize_label(b["label"])
        cos = (cosine_similarity(a["embedding"], b["embedding"])
               if a.get("embedding") and b.get("embedding") else 0.0)
        if lexical or cos > _COSINE_DUP:
            dups.append(f"{a['label']!r} ~ {b['label']!r}"
                        f" ({'label' if lexical else f'cos={cos:.2f}'})")
    # Rate per NODE, not per C(n,2) pair: the pair denominator grows
    # quadratically, so at 28 nodes a 0.05 threshold tolerated 18 duplicate
    # pairs — near-vacuous (roadmap §4.4). Per node, 0.05 tolerates ~1 dup
    # pair at 28 nodes. Frozen scenarios use `concepts` instead; this check
    # remains for the legacy generator scenarios.
    rate = len(dups) / len(nodes) if nodes else 0.0
    return CheckResult(name="dedup", metrics={"duplicate_label_rate": rate},
                       passed=rate <= ctx.threshold(0.05), details=dups)
