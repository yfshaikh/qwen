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
    rate = len(dups) / len(pairs) if pairs else 0.0
    return CheckResult(name="dedup", metrics={"duplicate_label_rate": rate},
                       passed=rate <= ctx.threshold(0.05), details=dups)
