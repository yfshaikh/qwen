"""DashScope embeddings adapter over the OpenAI-compatible endpoint
(implements core.ports.EmbedderPort). text-embedding-v3 at 1024 dims matches
the pgvector `vector(1024)` column."""

from __future__ import annotations

from typing import Any, Protocol

# DashScope caps embedding requests at 10 texts each; larger inputs are
# chunked transparently.
_MAX_BATCH = 10


class _AsyncEmbeddingsClient(Protocol):
    @property
    def embeddings(self) -> Any: ...


class OpenAIEmbedder:
    """Implements core.ports.EmbedderPort against an OpenAI-compatible embeddings API."""

    def __init__(
        self,
        client: _AsyncEmbeddingsClient,
        model: str,
        dimensions: int | None = 1024,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _MAX_BATCH):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "input": texts[i : i + _MAX_BATCH],
            }
            if self._dimensions is not None:
                kwargs["dimensions"] = self._dimensions
            resp = await self._client.embeddings.create(**kwargs)
            out.extend(item.embedding for item in resp.data)
        return out


def build_embedder(settings: Any) -> OpenAIEmbedder:
    """Composition helper: build the DashScope embedder from Settings."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )
    return OpenAIEmbedder(
        client=client,
        model=settings.model_for("embedder"),
        dimensions=settings.embedding_dim,
    )
