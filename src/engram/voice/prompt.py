"""Spoken-tutor prompt assembly. Concise, spoken register, grounded in recalled
memory. Mirrors engram.tutor.prompt.compose but tuned for voice."""

from __future__ import annotations

from engram.core.models import Message

SYSTEM = (
    "You are a concise spoken tutor. Keep replies short and conversational — "
    "two or three sentences, no markdown, no lists. Ground every answer in what "
    "you remember about this learner (below). If they are weak on a concept, "
    "gently target it first."
)


def compose_voice(text_block: str, history: list[dict], user_text: str) -> list[Message]:
    msgs = [Message(role="system", content=SYSTEM)]
    if text_block:
        msgs.append(Message(role="system", content=f"What you remember:\n{text_block}"))
    for m in history:
        msgs.append(Message(role=m["role"], content=m["content"]))
    msgs.append(Message(role="user", content=user_text))
    return msgs
