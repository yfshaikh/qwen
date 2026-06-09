"""Text tutor host adapter — the demo surface (DESIGN §4.3 tutor agent).

A minimal, text-only stand-in for the Starnotes push-to-talk voice loop (voice
needs STT/TTS providers outside this POC's OpenRouter-only scope; the memory
integration is identical). One turn:

    recall → compose (cached system prefix + recalled memory + message)
           → one streamed tutor LLM call → emit LearningEvents as a side effect

The tutor never writes the graph directly; it only emits events. Consolidation
happens out-of-band (the "consolidate now" button or the cron sweep).
"""

from __future__ import annotations

from typing import Any

from engram.core.models import LearningEvent, Message
from engram.core.service import EngramService

# Stable, cacheable system prefix (DESIGN §6: ~80% prompt-prefix savings). The
# per-turn recalled-memory block is appended separately so this stays constant.
_SYSTEM_PREFIX = (
    "You are a patient, concise tutor. You have a memory of this learner, recalled "
    "below. Use it: do NOT re-explain concepts they have already mastered; build on "
    "what they know; honor their stated preferences; and reconnect related ideas they "
    "have seen before. If the memory is empty, just answer normally."
)


class TextTutor:
    def __init__(self, service: EngramService, *, recall_budget: int = 500) -> None:
        self.service = service
        self.recall_budget = recall_budget

    async def turn(
        self,
        learner_id: str,
        message: str,
        *,
        session_id: str | None = None,
        doc_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 1. Recall the token-budgeted subgraph for this message (no LLM reasoning).
        recall = await self.service.recall(learner_id, message, self.recall_budget)

        # 2. Compose: cached prefix + recalled memory + the learner's message.
        memory_block = recall.text_block or "(no memory yet for this learner)"
        messages = [
            Message(role="system", content=_SYSTEM_PREFIX),
            Message(role="system", content=f"Recalled memory of the learner:\n{memory_block}"),
            Message(role="user", content=message),
        ]

        # 3. One tutor call (vision-capable model in production; text here).
        completion = await self.service.llm.complete(role="tutor", messages=messages)
        reply = completion.text or ""

        # 4. Emit events as a side effect (the tutor does not write the graph).
        refs: dict[str, Any] = dict(doc_ref or {})
        if session_id:
            refs["session_id"] = session_id
        events = [
            LearningEvent(learner_id=learner_id, type="asked_about", text=message, refs=refs),
            LearningEvent(
                learner_id=learner_id, type="tutor_explanation", text=reply, refs=refs
            ),
        ]
        await self.service.ingest(events)

        return {
            "reply": reply,
            "recall": {"text_block": recall.text_block, "subgraph": recall.subgraph},
            "events_emitted": len(events),
        }
