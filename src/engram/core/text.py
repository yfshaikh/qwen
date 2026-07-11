"""Pure text helpers shared by Keeper merging (spec 2) and eval checks. Stdlib only."""
from __future__ import annotations

import re

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")


def normalize_label(s: str) -> str:
    out = _PUNCT.sub(" ", s.casefold())
    out = _WS.sub(" ", out).strip()
    if not out:
        return out
    words = out.split(" ")
    last = words[-1]
    if len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        words[-1] = last[:-1]  # naive depluralize: transistors -> transistor
    return " ".join(words)


def token_jaccard(a: str, b: str) -> float:
    """Jaccard overlap of normalized label tokens; 0.0 when either side is empty."""
    ta = set(normalize_label(a).split())
    tb = set(normalize_label(b).split())
    ta.discard("")
    tb.discard("")
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
