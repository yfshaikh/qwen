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
