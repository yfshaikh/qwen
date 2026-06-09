"""Embedding adapters.

`HashingEmbedder` is the default: a deterministic, dependency-light feature-
hashing embedder that needs no API key or network and gives meaningful cosine
similarity for texts that share vocabulary. It is a legitimate, swappable
`embed()` implementation behind the LLM port (DESIGN §4.6) — good enough to make
recall/vector-search runnable offline; swap to `OpenAICompatEmbedder` for
production-quality semantic embeddings via config.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class HashingEmbedder:
    """Signed feature hashing -> L2-normalized vector. Deterministic, offline."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float64)
        toks = _tokens(text)
        if not toks:
            return v.tolist()
        for tok in toks:
            h = hashlib.sha1(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) else -1.0
            v[idx] += sign
        norm = float(np.linalg.norm(v))
        if norm > 0.0:
            v /= norm
        return v.tolist()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class OpenAICompatEmbedder:
    """Embeddings via any OpenAI-compatible `/embeddings` endpoint."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in resp.data]


def build_embedder(settings: Any) -> Embedder:
    """Pick an embedder from Settings: 'local' (default) or 'api'."""
    if getattr(settings, "embedder_kind", "local") == "api":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.embeddings_api_key or settings.openrouter_api_key or "missing",
            base_url=settings.embeddings_base_url or settings.openrouter_base_url,
        )
        return OpenAICompatEmbedder(client=client, model=settings.model_for("embedder"))
    return HashingEmbedder(dim=settings.embedding_dim)
