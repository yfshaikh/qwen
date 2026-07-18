from pathlib import Path

from engram.adapters.seed import seed_graph
from tests.fakes import FakeEmbedder, FakeStorage

FIXTURE = Path(__file__).parent / "fixtures" / "seed_basic.yaml"


async def test_seed_graph_loads_nodes_edges_evidence():
    fs = FakeStorage()
    emb = FakeEmbedder(dim=1024)
    key_to_id = await seed_graph(fs, emb, FIXTURE)

    assert set(key_to_id) == {"limits", "derivatives"}
    assert len(fs.nodes) == 2
    assert len(fs.edges) == 1
    assert len(fs.evidence) == 1

    limits = fs.nodes[key_to_id["limits"]]
    assert limits.label == "Limits"
    assert limits.embedding is not None and len(limits.embedding) == 1024
    assert fs.edges[0].source_id == key_to_id["limits"]
    assert fs.edges[0].target_id == key_to_id["derivatives"]
    assert fs.evidence[0].content.startswith("Correctly evaluated")
