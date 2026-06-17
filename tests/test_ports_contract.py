from engram.core.ports import EmbedderPort, HostPort, LLMPort, StoragePort
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def test_fakes_satisfy_ports():
    # runtime_checkable Protocols: isinstance checks method presence.
    assert isinstance(FakeLLM(), LLMPort)
    assert isinstance(FakeEmbedder(), EmbedderPort)
    assert isinstance(FakeStorage(), StoragePort)


def test_host_port_methods_exist():
    # HostPort is the facade contract; assert its method names are declared.
    for name in ("ingest", "recall", "consolidate", "graph"):
        assert hasattr(HostPort, name)


async def test_fake_llm_records_calls():
    llm = FakeLLM(canned_text="hi")
    from engram.core.models import Message

    out = await llm.complete("tutor", [Message(role="user", content="q")])
    assert out.text == "hi"
    assert llm.complete_calls[0][0] == "tutor"


async def test_fake_embedder_returns_dim_vectors():
    emb = FakeEmbedder(dim=8)
    vecs = await emb.embed(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 8
    assert emb.embed_calls == [["a", "b"]]


async def test_fake_storage_event_insert_and_count():
    from engram.core.models import LearningEvent

    fs = FakeStorage()
    ids = await fs.insert_events(
        [LearningEvent(learner_id="a", type="utterance", text="hi")]
    )
    assert len(ids) == 1
    assert len(fs.events) == 1
    assert fs.events[0].consolidated_at is None


async def test_fake_storage_graph_insert_and_reads():
    from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Node, NodeType

    fs = FakeStorage()
    a = await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0, 0.0])
    )
    b = await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="B", embedding=[0.0, 1.0])
    )
    await fs.insert_edge(
        Edge(learner_id="a", source_id=a, target_id=b, type=EdgeType.PREREQUISITE)
    )
    await fs.insert_evidence(
        Evidence(node_id=a, kind=EvidenceKind.QUIZ_CORRECT, content="ok", importance=0.9)
    )

    seeds = await fs.vector_search("a", [1.0, 0.0], k=1)
    assert [n.label for n in seeds] == ["A"]  # nearest to [1,0]

    edges = await fs.get_edges("a", [a])
    assert len(edges) == 1 and edges[0].target_id == b

    nodes = await fs.get_nodes("a", [b])
    assert [n.label for n in nodes] == ["B"]

    ev = await fs.top_evidence([a], per_node=2)
    assert ev[a][0].content == "ok"


async def test_fake_vector_search_excludes_forgotten():
    from datetime import datetime, timezone

    from engram.core.models import Node, NodeType

    fs = FakeStorage()
    await fs.insert_node(
        Node(
            learner_id="a",
            type=NodeType.CONCEPT,
            label="Gone",
            embedding=[1.0, 0.0],
            forgotten_at=datetime.now(timezone.utc),
        )
    )
    await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Here", embedding=[1.0, 0.0])
    )
    seeds = await fs.vector_search("a", [1.0, 0.0], k=5)
    assert [n.label for n in seeds] == ["Here"]
