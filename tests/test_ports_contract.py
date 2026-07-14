from engram.core.ports import EmbedderPort, LLMPort, StoragePort
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def test_fakes_satisfy_ports():
    # runtime_checkable Protocols: isinstance checks method presence.
    assert isinstance(FakeLLM(), LLMPort)
    assert isinstance(FakeEmbedder(), EmbedderPort)
    assert isinstance(FakeStorage(), StoragePort)


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


async def test_fake_get_pending_events_and_ids():
    from engram.core.models import LearningEvent

    fs = FakeStorage()
    await fs.insert_events(
        [LearningEvent(learner_id="a", type="utterance", text="hi")]
    )
    pending = await fs.get_pending_events("a")
    assert len(pending) == 1 and pending[0].id is not None


async def test_fake_consolidation_lock_blocks_second_acquire():
    fs = FakeStorage()
    async with fs.consolidation_lock("a") as first:
        assert first is True
        async with fs.consolidation_lock("a") as second:
            assert second is False
    async with fs.consolidation_lock("a") as again:
        assert again is True


async def test_fake_apply_consolidation_remaps_temp_ids_and_watermarks():
    from engram.core.consolidation import ConsolidationPlan
    from engram.core.models import Evidence, EvidenceKind, LearningEvent, Node, NodeType

    fs = FakeStorage()
    ids = await fs.insert_events([LearningEvent(learner_id="a", type="note", text="n")])

    new_node = Node(id="tmp-0", learner_id="a", type=NodeType.CONCEPT, label="X",
                    salience=1.0, embedding=[1.0, 0.0])
    plan = ConsolidationPlan(
        learner_id="a",
        new_nodes=[new_node],
        new_evidence=[Evidence(node_id="tmp-0", kind=EvidenceKind.NOTE, content="c")],
        processed_event_ids=ids,
    )
    await fs.apply_consolidation(plan)

    assert len(fs.nodes) == 1
    real_id = next(iter(fs.nodes))
    assert real_id != "tmp-0"  # remapped
    assert fs.evidence[0].node_id == real_id
    assert (await fs.get_pending_events("a")) == []  # watermarked


async def test_fake_get_audit_orders_filters_and_scopes():
    from engram.core.consolidation import AuditEntry, ConsolidationPlan

    fs = FakeStorage()
    await fs.apply_consolidation(
        ConsolidationPlan(learner_id="a", audit=[AuditEntry(op="extract"), AuditEntry(op="link")])
    )
    await fs.apply_consolidation(
        ConsolidationPlan(learner_id="other", audit=[AuditEntry(op="consolidate")])
    )

    rows = await fs.get_audit("a")
    assert [r["op"] for r in rows] == ["extract", "link"]
    assert rows[0]["ts"] < rows[1]["ts"]
    assert set(rows[0]) == {"id", "op", "rationale", "model", "tokens", "cost", "ts"}

    after = await fs.get_audit("a", since=rows[0]["ts"])
    assert [r["op"] for r in after] == ["link"]

    assert len(await fs.get_audit("a", limit=1)) == 1
    assert await fs.get_audit("nobody") == []


async def test_fake_last_event_at_matches_old_max_ts_derivation():
    from datetime import datetime, timedelta, timezone

    from engram.core.models import LearningEvent

    fs = FakeStorage()
    assert await fs.last_event_at("a") is None  # no events yet

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await fs.insert_events([
        LearningEvent(learner_id="a", type="utterance", text="first", ts=t0),
        LearningEvent(learner_id="a", type="utterance", text="second", ts=t0 + timedelta(days=1)),
        LearningEvent(learner_id="other", type="utterance", text="x", ts=t0 + timedelta(days=5)),
    ])
    # old derivation: max(ts) over the learner's own events
    expected = max(e.ts for e in fs.events if e.learner_id == "a")
    assert await fs.last_event_at("a") == expected == t0 + timedelta(days=1)


async def test_fake_count_voice_sessions_matches_old_len_derivation():
    fs = FakeStorage()
    assert await fs.count_voice_sessions("a") == 0

    await fs.create_voice_session("a")
    await fs.create_voice_session("a")
    await fs.create_voice_session("other")

    # old derivation: len(await list_voice_sessions(learner_id, 1000))
    expected = len(await fs.list_voice_sessions("a", 1000))
    assert expected == 2
    assert await fs.count_voice_sessions("a") == expected


async def test_fake_get_live_nodes_with_embedding_false_strips_embedding():
    from engram.core.models import Node, NodeType

    fs = FakeStorage()
    nid = await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0, 0.0])
    )
    lite = await fs.get_live_nodes("a", with_embedding=False)
    assert lite[0].embedding is None and lite[0].label == "A"

    default = await fs.get_live_nodes("a")
    assert default[0].embedding == [1.0, 0.0]
    # the stored node itself must be untouched by the lite copy
    assert fs.nodes[nid].embedding == [1.0, 0.0]


async def test_fake_get_all_nodes_with_embedding_false_strips_embedding():
    from engram.core.models import Node, NodeType

    fs = FakeStorage()
    await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="A", embedding=[1.0, 0.0])
    )
    lite = await fs.get_all_nodes("a", with_embedding=False)
    assert lite[0].embedding is None

    default = await fs.get_all_nodes("a")
    assert default[0].embedding == [1.0, 0.0]


async def test_fake_top_evidence_with_embedding_false_strips_embedding():
    from engram.core.models import Evidence, EvidenceKind

    fs = FakeStorage()
    await fs.insert_evidence(
        Evidence(node_id="a", kind=EvidenceKind.QUIZ_CORRECT, content="ok",
                 importance=0.9, embedding=[1.0, 0.0])
    )
    lite = await fs.top_evidence(["a"], per_node=2, with_embedding=False)
    assert lite["a"][0].content == "ok"
    assert lite["a"][0].embedding is None

    default = await fs.top_evidence(["a"], per_node=2)
    assert default["a"][0].embedding == [1.0, 0.0]


async def test_fake_llm_stream_yields_canned_text_in_chunks():
    from engram.core.models import Message

    llm = FakeLLM(canned_text="hello world")
    out = [d async for d in llm.stream("tutor", [Message(role="user", content="q")])]
    assert "".join(out) == "hello world"
    assert llm.stream_calls[0][0] == "tutor"
