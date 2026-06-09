"""Memory Keeper consolidation — driven by a scripted FakeLLM (no network/DB).

The extractor's output is canned per-consolidation via FakeLLM.responder; the
embedder is the deterministic HashingEmbedder so link/merge/vector steps are
reproducible. Identical item text → identical embedding → cosine 1.0, so a
repeat item reliably MERGES into its existing node.
"""

from __future__ import annotations

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.keeper import Keeper
from engram.core.models import Completion, LearningEvent, Node, NodeType
from tests.fakes import FakeLLM

DIM = 64


def _llm(payloads: list[dict]) -> FakeLLM:
    """FakeLLM whose extractor returns the next queued payload as Completion.json."""
    seq = iter(payloads)

    def responder(role, messages, schema):
        if role == "extractor":
            return Completion(json=next(seq), model="fake-extractor", usage={"total_tokens": 7})
        return Completion(text="ok")

    return FakeLLM(responder=responder, embedder=HashingEmbedder(DIM))


def _item(label, observation, kind="struggle", importance=0.8, summary="s"):
    return {
        "type": "concept",
        "label": label,
        "summary": summary,
        "observation": observation,
        "evidence": [{"kind": kind, "content": f"{kind} on {label}", "importance": importance}],
    }


async def test_basic_consolidation_creates_graph():
    s = InMemoryStorage()
    llm = _llm([{"items": [_item("derivatives", 0.5)]}])
    keeper = Keeper(s, llm, embed_dim=DIM)
    await s.insert_event(LearningEvent(learner_id="alice", type="utterance", text="chain rule?"))

    stats = await keeper.consolidate("alice")

    assert stats["events_processed"] == 1
    assert stats["nodes_created"] == 1
    nodes = await s.get_nodes("alice", types=["concept"])
    assert len(nodes) == 1 and nodes[0].label == "derivatives"
    assert abs(nodes[0].mastery - 0.5) < 1e-9  # EWMA seed: 0.3*0.5 + 0.7*0.5
    assert len(await s.get_evidence(nodes[0].id)) == 1
    ops = {a.op for a in await s.get_audit("alice")}
    assert {"extract", "link", "consolidate"} <= ops
    assert await s.count_pending_events("alice") == 0


async def test_second_consolidation_with_no_events_is_noop():
    s = InMemoryStorage()
    llm = _llm([{"items": [_item("derivatives", 0.5)]}])
    keeper = Keeper(s, llm, embed_dim=DIM)
    await s.insert_event(LearningEvent(learner_id="alice", type="utterance"))
    await keeper.consolidate("alice")

    stats2 = await keeper.consolidate("alice")
    assert stats2["events_processed"] == 0
    assert stats2["nodes_created"] == 0


async def test_ewma_mastery_update_on_merge():
    s = InMemoryStorage()
    llm = _llm([
        {"items": [_item("derivatives", 0.5)]},
        {"items": [_item("derivatives", 0.9)]},
    ])
    keeper = Keeper(s, llm, embed_dim=DIM)

    await s.insert_event(LearningEvent(learner_id="alice", type="utterance"))
    await keeper.consolidate("alice")  # mastery -> 0.5

    await s.insert_event(LearningEvent(learner_id="alice", type="quiz_result"))
    stats = await keeper.consolidate("alice")  # merges, EWMA: 0.3*0.9 + 0.7*0.5 = 0.62

    nodes = await s.get_nodes("alice", types=["concept"])
    assert len(nodes) == 1  # merged, not duplicated
    assert stats["nodes_updated"] >= 1
    assert abs(nodes[0].mastery - 0.62) < 1e-9


async def test_contradiction_is_detected_and_audited():
    s = InMemoryStorage()
    llm = _llm([
        {"items": [_item("derivatives", 0.1)]},
        {"items": [_item("derivatives", 0.9, kind="demonstrated")]},
    ])
    keeper = Keeper(s, llm, embed_dim=DIM)

    await s.insert_event(LearningEvent(learner_id="alice", type="utterance"))
    await keeper.consolidate("alice")  # mastery -> 0.1

    await s.insert_event(LearningEvent(learner_id="alice", type="demo"))
    await keeper.consolidate("alice")  # demonstrated 0.9 vs 0.1 -> contradiction

    ops = [a.op for a in await s.get_audit("alice")]
    assert "resolve_contradiction" in ops
    node = (await s.get_nodes("alice", types=["concept"]))[0]
    assert abs(node.mastery - 0.34) < 1e-9  # 0.3*0.9 + 0.7*0.1


async def test_untouched_node_decays_and_is_pruned():
    s = InMemoryStorage()
    emb = (await HashingEmbedder(DIM).embed(["photosynthesis"]))[0]
    stale_id = await s.upsert_node(
        Node(learner_id="alice", type=NodeType.CONCEPT, label="photosynthesis",
             salience=0.1, embedding=emb)
    )
    # Aggressive decay so the untouched node drops below the prune floor in one pass.
    keeper = Keeper(s, _llm([{"items": [_item("derivatives", 0.7)]}]), decay=0.4, embed_dim=DIM)
    await s.insert_event(LearningEvent(learner_id="alice", type="utterance"))

    stats = await keeper.consolidate("alice")

    assert stats["pruned"] >= 1
    stale = await s.get_node(stale_id)
    assert stale.forgotten_at is not None  # soft-deleted, not removed
    ops = {a.op for a in await s.get_audit("alice")}
    assert "prune" in ops


async def test_malformed_extraction_is_tolerated():
    s = InMemoryStorage()
    llm = _llm([
        {"items": [
            {"type": "invented_type", "label": "x"},          # bad type -> skipped
            {"type": "concept"},                                # no label -> skipped
            {"type": "concept", "label": "ok", "observation": "garbage",
             "evidence": [{"kind": "nope", "content": "y"}, "not-a-dict"]},
        ]},
    ])
    keeper = Keeper(s, llm, embed_dim=DIM)
    await s.insert_event(LearningEvent(learner_id="alice", type="utterance"))

    stats = await keeper.consolidate("alice")

    assert stats["nodes_created"] == 1  # only the salvageable item landed
    node = (await s.get_nodes("alice"))[0]
    assert node.label == "ok"
    assert node.mastery is None  # garbage observation coerced to None
    assert await s.get_evidence(node.id) == []  # bad evidence kinds skipped
