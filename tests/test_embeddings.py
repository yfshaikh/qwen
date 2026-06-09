from engram.adapters.llm.embeddings import HashingEmbedder


async def test_hashing_embedder_is_deterministic_and_sized():
    emb = HashingEmbedder(dim=256)
    a1, a2 = await emb.embed(["derivatives and limits"]), await emb.embed(["derivatives and limits"])
    assert a1 == a2
    assert len(a1[0]) == 256


async def test_hashing_embedder_empty_is_zero_vector():
    emb = HashingEmbedder(dim=64)
    [vec] = await emb.embed([""])
    assert vec == [0.0] * 64


def _cosine(a, b):
    import numpy as np

    va, vb = np.asarray(a), np.asarray(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


async def test_shared_vocabulary_is_more_similar():
    emb = HashingEmbedder(dim=2048)
    near = await emb.embed(
        ["the chain rule for derivatives", "derivatives and the chain rule"]
    )
    far = await emb.embed(
        ["the chain rule for derivatives", "photosynthesis in green plants"]
    )
    assert _cosine(near[0], near[1]) > _cosine(far[0], far[1])
