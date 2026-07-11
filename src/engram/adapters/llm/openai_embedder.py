"""OpenAI embeddings adapter (implements core.ports.EmbedderPort).

Separate from the chat LLM because OpenRouter has no embeddings endpoint. The
`dimensions` param truncates text-embedding-3-* to the configured size (1024) so
it matches the pgvector column. DashScope's text-embedding-v4 is a drop-in swap
later (same EmbedderPort).
"""

from __future__ import annotations

from typing import Any, Protocol


class _AsyncEmbeddingsClient(Protocol):
    @property
    def embeddings(self) -> Any: ...


class OpenAIEmbedder:
    """Implements core.ports.EmbedderPort against the OpenAI embeddings API."""

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
        kwargs: dict[str, Any] = {"model": self._model, "input": texts}
        if self._dimensions is not None:
            kwargs["dimensions"] = self._dimensions
        resp = await self._client.embeddings.create(**kwargs)
        return [item.embedding for item in resp.data]


def build_embedder(settings: Any) -> OpenAIEmbedder:
    """Composition helper: build the OpenAI embedder from Settings."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    return OpenAIEmbedder(
        client=client,
        model=settings.model_for("embedder"),
        dimensions=settings.embedding_dim,
    )
