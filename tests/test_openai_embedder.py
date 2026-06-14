from engram.adapters.llm.openai_embedder import OpenAIEmbedder


class _FakeItem:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbResponse:
    def __init__(self, vectors):
        self.data = [_FakeItem(v) for v in vectors]


class _FakeEmbeddings:
    def __init__(self, recorder):
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder["kwargs"] = kwargs
        n = len(kwargs["input"])
        dim = kwargs.get("dimensions", 3)
        return _FakeEmbResponse([[0.1] * dim for _ in range(n)])


class _FakeClient:
    def __init__(self, recorder):
        self.embeddings = _FakeEmbeddings(recorder)


async def test_embed_passes_model_input_and_dimensions():
    rec = {}
    emb = OpenAIEmbedder(
        client=_FakeClient(rec), model="text-embedding-3-small", dimensions=1024
    )
    vecs = await emb.embed(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    assert rec["kwargs"]["model"] == "text-embedding-3-small"
    assert rec["kwargs"]["input"] == ["a", "b"]
    assert rec["kwargs"]["dimensions"] == 1024


async def test_embed_omits_dimensions_when_none():
    rec = {}
    emb = OpenAIEmbedder(client=_FakeClient(rec), model="m", dimensions=None)
    await emb.embed(["x"])
    assert "dimensions" not in rec["kwargs"]
