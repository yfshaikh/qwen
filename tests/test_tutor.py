"""TextTutor host adapter — recall → reply → emit events (no DB/network)."""

from __future__ import annotations

from engram.adapters.host.text_tutor import TextTutor
from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.service import EngramService
from tests.fakes import FakeLLM


async def test_tutor_turn_uses_recall_and_emits_events():
    storage = InMemoryStorage()
    llm = FakeLLM(canned_text="Here's a hint.", embedder=HashingEmbedder(64))
    tutor = TextTutor(EngramService(storage, llm, embed_dim=64))

    out = await tutor.turn("alice", "what is a derivative?", session_id="s1")

    assert out["reply"] == "Here's a hint."
    assert out["events_emitted"] == 2
    assert "text_block" in out["recall"] and "subgraph" in out["recall"]

    pending = await storage.fetch_unconsolidated_events("alice")
    assert sorted(e.type for e in pending) == ["asked_about", "tutor_explanation"]
    assert any(e.refs.get("session_id") == "s1" for e in pending)
    # The tutor issued a "tutor"-role completion that saw the learner's message.
    assert llm.complete_calls and llm.complete_calls[-1][0] == "tutor"
    assert any(m.content == "what is a derivative?" for m in llm.complete_calls[-1][1])
