"""Golden wire shapes: the SDK typing work must not change any JSON payload
(except the additive graph-node `importance` key). These tests pin the shapes
consumers (qwen console, Marfini frontend) already depend on."""
import json

from engram.core.models import Evidence, EvidenceKind, Node, NodeType
from engram.core.recall import Recall, RecallWeights
from engram.core.graph import build_graph
from engram.core.tokens import heuristic_token_count
from tests.fakes import FakeEmbedder, FakeStorage

RECALL_NODE_KEYS = {"id", "external_id", "type", "label", "mastery", "confidence",
                    "salience", "importance", "score", "scores", "evidence"}
RECALL_EDGE_KEYS = {"id", "source", "target", "type", "weight"}
GRAPH_NODE_KEYS = {"id", "external_id", "label", "type", "summary", "mastery",
                   "confidence", "salience", "importance", "evidence"}


async def _seeded():
    # Two LINKED nodes: the edge shape is the one thing this plan re-declares
    # twice (SubgraphEdge/GraphEdge) — it must actually be pinned, not vacuous.
    from engram.core.models import Edge, EdgeType
    storage = FakeStorage()
    a = await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT,
                                       label="A", mastery=0.5, salience=0.5,
                                       importance=0.7, embedding=[1.0] * 8))
    b = await storage.insert_node(Node(learner_id="L", type=NodeType.CONCEPT,
                                       label="B", mastery=0.5, salience=0.5,
                                       embedding=[1.0] * 8))
    await storage.insert_edge(Edge(learner_id="L", source_id=a, target_id=b,
                                   type=EdgeType.RELATES_TO))
    await storage.insert_evidence(Evidence(node_id=a, kind=EvidenceKind.NOTE,
                                           content="c", importance=0.9))
    return storage


async def test_recall_subgraph_wire_shape_unchanged():
    storage = await _seeded()
    r = Recall(storage, FakeEmbedder(dim=8), heuristic_token_count, RecallWeights())
    res = await r.run("L", "query", 800)
    json.dumps(res.subgraph)  # still plain JSON-serializable dicts
    assert set(res.subgraph.keys()) == {"nodes", "edges"}
    assert set(res.subgraph["nodes"][0].keys()) == RECALL_NODE_KEYS
    assert isinstance(res.subgraph["nodes"][0]["scores"], dict)
    assert res.subgraph["edges"], "seed must produce an edge — the pin is not optional"
    assert set(res.subgraph["edges"][0].keys()) == RECALL_EDGE_KEYS


async def test_graph_wire_shape_gains_importance_only():
    storage = await _seeded()
    gv = await build_graph(storage, "L")
    json.dumps({"nodes": gv.nodes, "edges": gv.edges})
    node_a = next(n for n in gv.nodes if n["label"] == "A")
    assert set(node_a.keys()) == GRAPH_NODE_KEYS
    assert node_a["importance"] == 0.7
    assert gv.edges, "seed must produce an edge"
    assert set(gv.edges[0].keys()) == RECALL_EDGE_KEYS


async def test_audit_rows_typed_and_cost_is_float():
    from decimal import Decimal
    from engram.core.consolidation import AuditEntry, ConsolidationPlan
    from engram.core.engram import Engram
    from tests.fakes import FakeLLM

    storage = FakeStorage()
    await storage.apply_consolidation(ConsolidationPlan(
        learner_id="L",
        audit=[AuditEntry(op="merge", rationale="r", cost=Decimal("0.5"))]))
    eng = Engram(storage=storage, llm=FakeLLM(), embedder=FakeEmbedder(dim=8))
    rows = await eng.audit("L")
    assert rows and isinstance(rows[0], dict)  # TypedDict IS a dict at runtime
    assert rows[0]["op"] == "merge"
    assert isinstance(rows[0]["cost"], float) and rows[0]["cost"] == 0.5
    assert rows[0]["ts"] is not None  # datetime, host serializes
    json.dumps({**rows[0], "ts": None})  # everything else JSON-native
