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


def canonical_label(current: str, candidate: str) -> str:
    """Pick the more canonical surface form when two labels name the SAME merged
    concept: prefer more word tokens, then more letters, else keep `current`
    (stability — don't churn a label on a tie). So an abbreviation loses to its
    expansion: canonical_label("EM Induction", "Electromagnetic Induction") ->
    "Electromagnetic Induction".

    # ponytail: word-count/letter-count heuristic. It expands abbreviations but
    # can't know domain canonicity ("colour" vs "color"); swap for an alias table
    # if it misfires. Only ever runs on labels already judged the same concept by
    # the merge, so it cannot make a merge worse — only choose its display name.
    """
    def score(s: str) -> tuple[int, int]:
        words = [w for w in normalize_label(s).split(" ") if w]
        return (len(words), sum(len(w) for w in words))

    cur = current.strip()
    cand = candidate.strip()
    if not cand:
        return cur
    if not cur:
        return cand
    return cand if score(cand) > score(cur) else cur
