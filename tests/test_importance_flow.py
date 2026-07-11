"""Extractor importance -> Keeper EWMA on the node -> recall scoring (#3)."""
import json

from engram.core.engram import Engram
from engram.core.models import Completion, LearningEvent, Message, Node, NodeType
from engram.core.recall import Recall, RecallWeights
from engram.core.tokens import heuristic_token_count
from tests.fakes import FakeEmbedder, FakeStorage


class _OneShotLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, role: str, messages: list[Message], schema=None) -> Completion:
        return Completion(text=self._text if role == "extractor" else "no")


EXTRACTION = json.dumps({
    "concepts": [{
        "label": "Faraday Law", "summary": "s", "importance": 0.9,
        "evidence": [{"kind": "asked_about", "content": "q", "importance": 0.7}],
    }],
    "preferences": [], "goals": [], "relations": [],
})


async def test_keeper_sets_node_importance_from_evidence():
    storage = FakeStorage()
    eng = Engram(storage=storage, llm=_OneShotLLM(EXTRACTION), embedder=FakeEmbedder(dim=8))
    await eng.ingest([LearningEvent(learner_id="L", type="utterance", text="hi")])
    await eng.consolidate("L")
    node = (await storage.get_live_nodes("L"))[0]
    # seeded from concept importance 0.9, then EWMA'd with evidence 0.7 (alpha 0.3)
    assert node.importance is not None
    assert 0.7 <= node.importance <= 0.9


async def test_recall_prefers_high_node_importance():
    storage = FakeStorage()
    # identical embeddings/salience; only node importance differs
    for label, imp in (("aaaa", 0.05), ("bbbb", 0.95)):
        await storage.insert_node(Node(
            learner_id="L", type=NodeType.CONCEPT, label=label, salience=0.5,
            importance=imp, embedding=[1.0] * 8))
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count,
               RecallWeights(recency=0.0, importance=1.0, relevance=0.0))
    res = await r.run("L", "query", 800)
    assert res.subgraph["nodes"][0]["label"] == "bbbb"
    assert res.subgraph["nodes"][0]["importance"] == 0.95


async def test_recall_null_importance_gets_neutral_prior():
    storage = FakeStorage()
    await storage.insert_node(Node(
        learner_id="L", type=NodeType.CONCEPT, label="old", salience=0.5,
        embedding=[1.0] * 8))
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count,
               RecallWeights(recency=0.0, importance=1.0, relevance=0.0))
    res = await r.run("L", "query", 800)
    assert res.subgraph["nodes"][0]["scores"]["importance"] == 0.3
