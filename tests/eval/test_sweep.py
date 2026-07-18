"""Config sweeps: Tier-1 re-scoring (recall weights only); Tier-2 rebuilding."""
from engram.eval.fixtures import snapshot_graph
from engram.eval.scenario import Probe
from engram.eval.sweep import expand_grid, run_tier1_sweep, weights_from_combo
from engram.core.recall import RecallWeights
from engram.core.models import Node, NodeType
from tests.fakes import FakeEmbedder, FakeStorage


def test_expand_grid_cartesian():
    combos = expand_grid({"recall_w_relevance": [0.4, 0.6], "recall_seed_k": [4]})
    assert combos == [
        {"recall_w_relevance": 0.4, "recall_seed_k": 4},
        {"recall_w_relevance": 0.6, "recall_seed_k": 4},
    ]


def test_weights_from_combo_overrides_only_present():
    w = weights_from_combo({"recall_w_relevance": 0.9}, RecallWeights())
    assert w.relevance == 0.9 and w.recency == 0.3 and w.importance == 0.3


async def test_run_tier1_sweep_picks_best_and_tears_down():
    # Build a one-node graph so recall is deterministic.
    src = FakeStorage()
    await src.insert_node(Node(learner_id="o", type=NodeType.CONCEPT, label="Limit",
                               salience=1.0, embedding=[1.0, 0.0]))
    graph = await snapshot_graph(src, "o")
    probes = [Probe(query="limit", expect_nodes=["Limit"], mastered_not_expected=[])]

    storage = FakeStorage()
    result = await run_tier1_sweep(storage, FakeEmbedder(dim=2), graph, probes,
                                   {"recall_w_relevance": [0.4, 0.6]})
    assert len(result["rows"]) == 2
    assert "node_hit_rate" in result["rows"][0]
    assert result["best"]["node_hit_rate"] == 1.0
    # every temp learner was deleted
    assert storage.nodes == {}
