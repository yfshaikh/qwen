"""EngramService end-to-end on the in-memory twin + scripted FakeLLM.

Exercises the full host surface: ingest → consolidate → graph/recall/evidence,
plus the cron sweep — all without a database or network.
"""

from __future__ import annotations

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import Completion, LearningEvent
from engram.core.service import EngramService
from tests.fakes import FakeLLM

DIM = 64

_EXTRACTION = {
    "items": [
        {
            "type": "concept",
            "label": "derivatives",
            "summary": "rate of change",
            "observation": 0.4,
            "evidence": [
                {"kind": "struggle", "content": "stuck on the chain rule", "importance": 0.8}
            ],
        }
    ]
}


def _service(payloads: list[dict]) -> EngramService:
    seq = iter(payloads)

    def responder(role, messages, schema):
        if role == "extractor":
            return Completion(json=next(seq), model="fake", usage={"total_tokens": 5})
        return Completion(text="ok")

    llm = FakeLLM(responder=responder, embedder=HashingEmbedder(DIM))
    return EngramService(InMemoryStorage(), llm, embed_dim=DIM)


async def test_ingest_consolidate_graph_recall_evidence():
    svc = _service([_EXTRACTION])

    ids = await svc.ingest([
        LearningEvent(learner_id="alice", type="utterance", text="what's a derivative?"),
        LearningEvent(learner_id="alice", type="utterance", text="I keep messing up the chain rule"),
    ])
    assert len(ids) == 2

    stats = await svc.consolidate("alice")
    assert stats["nodes_created"] == 1

    view = await svc.graph("alice")
    assert len(view.nodes) == 1
    node = view.nodes[0]
    assert node["label"] == "derivatives"
    assert node["evidence_count"] == 1
    assert "last_seen_at" in node and "forgotten_at" in node

    evidence = await svc.evidence(node["id"])
    assert len(evidence) == 1 and "chain rule" in evidence[0].content

    result = await svc.recall("alice", "help me with derivatives")
    assert "derivatives" in result.text_block
    assert result.subgraph["nodes"]


async def test_recall_empty_graph_is_empty():
    svc = _service([_EXTRACTION])
    result = await svc.recall("nobody", "anything")
    assert result.text_block == ""
    assert result.subgraph == {"nodes": [], "edges": []}


async def test_graph_focus_limits_to_neighborhood():
    svc = _service([
        {"items": [
            {"type": "concept", "label": "derivatives", "summary": "a",
             "observation": 0.5, "evidence": []},
            {"type": "concept", "label": "unrelated thing", "summary": "zzz",
             "observation": 0.5, "evidence": []},
        ]},
    ])
    await svc.ingest([LearningEvent(learner_id="alice", type="utterance", text="x")])
    await svc.consolidate("alice")

    full = await svc.graph("alice")
    focused = await svc.graph("alice", focus="derivatives", hops=1)
    assert len(focused.nodes) <= len(full.nodes)
    assert any(n["label"] == "derivatives" for n in focused.nodes)


async def test_consolidate_sweep_processes_quiet_learner():
    svc = _service([_EXTRACTION])
    await svc.ingest([LearningEvent(learner_id="alice", type="utterance", text="derivative help")])

    out = await svc.consolidate_sweep(quiet_seconds=0)
    assert "alice" in out["learners"]
    assert out["stats"]["alice"]["nodes_created"] == 1
    # Idempotent: a second sweep finds no pending events.
    out2 = await svc.consolidate_sweep(quiet_seconds=0)
    assert out2["learners"] == []
