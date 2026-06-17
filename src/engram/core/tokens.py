"""Pluggable token counting for Recall's budget fill.

Default is a cheap, provider-agnostic heuristic (~len/4). A real tokenizer can be
injected later behind the same TokenCounter signature without touching Recall.
"""

from __future__ import annotations

from collections.abc import Callable

TokenCounter = Callable[[str], int]


def heuristic_token_count(text: str) -> int:
    """Approximate token count as ceil(len/4), floored at 1."""
    return max(1, (len(text) + 3) // 4)
