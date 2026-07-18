"""Tutor prompt assembly. The stable SYSTEM_PREFIX comes first so the provider
can cache it; the per-turn memory block and conversation follow."""

from __future__ import annotations

from engram.core.models import Message

SYSTEM_PREFIX = (
    "You are a concise, encouraging tutor. Personalize using what you remember "
    "about the learner; don't re-explain what they already know. If memory is "
    "empty, teach normally. If the memory block lists 'Needs attention' concepts "
    "relevant to the question, address the weakest first before advancing."
)


def compose(text_block: str, turns: list[dict]) -> list[Message]:
    return [
        Message(role="system", content=SYSTEM_PREFIX),
        Message(role="system", content=f"Memory about the learner:\n{text_block or '(none yet)'}"),
        *[Message(role=t["role"], content=t["content"]) for t in turns],
    ]
