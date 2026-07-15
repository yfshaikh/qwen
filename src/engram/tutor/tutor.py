"""The Tutor — a host-layer consumer of the Engram facade. One turn:
recall → compose prompt → stream reply → emit raw events. Yields transport-
agnostic (event, data) frames; the /chat route formats them as SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from engram.core.models import LearningEvent
from engram.tutor.prompt import compose


class Tutor:
    def __init__(self, eng: Any) -> None:
        self.eng = eng

    async def turn(
        self, learner_id: str, messages: list[dict], budget: int | None = None
    ) -> AsyncIterator[tuple[str, dict]]:
        last = messages[-1] if messages else {}
        if not learner_id or last.get("role") != "user" or not last.get("content"):
            raise ValueError("chat requires learner_id and a non-empty user turn last")
        latest = last["content"]

        res = await self.eng.recall(learner_id, latest, budget)
        yield "context", {"text_block": res.text_block, "subgraph": res.subgraph}

        reply = ""
        prompt = compose(res.text_block, messages[-self.eng.history_turns:])
        async for delta in self.eng.llm.stream("tutor", prompt):
            reply += delta
            yield "delta", {"text": delta}

        events = [LearningEvent(learner_id=learner_id, type="utterance", text=latest)]
        if reply:
            events.append(
                LearningEvent(learner_id=learner_id, type="tutor_explanation", text=reply)
            )
        await self.eng.ingest(events)
        yield "saved", {"events": [{"type": e.type, "text": e.text} for e in events]}

        yield "done", {"reply": reply}
