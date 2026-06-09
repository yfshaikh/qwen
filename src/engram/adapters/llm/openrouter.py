"""OpenRouter LLMPort adapter — the swappable model-provider seam.

Wraps the OpenAI SDK pointed at OpenRouter's OpenAI-compatible endpoint
(https://openrouter.ai/api/v1). `complete()` goes to chat completions; `embed()`
delegates to an injected embedder (local by default — see `embeddings.py`), so
the whole pipeline runs without an embeddings provider. All model calls in
Engram flow through here; swapping a model is a config edit (DESIGN §4.7).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from engram.adapters.llm.embeddings import Embedder, build_embedder
from engram.core.models import Completion, Message


class _AsyncOpenAILike(Protocol):
    chat: Any


class OpenRouterLLM:
    """Implements core.ports.LLMPort against OpenRouter (OpenAI-compatible)."""

    def __init__(
        self,
        client: _AsyncOpenAILike,
        role_to_model: dict[str, str],
        embedder: Embedder,
    ) -> None:
        self._client = client
        self._role_to_model = role_to_model
        self._embedder = embedder

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        model = self._resolve(role)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if schema is not None:
            # OpenRouter passes json_object through to capable models; the prompt
            # must describe the schema (DESIGN). We parse the text into .json.
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content if resp.choices else None
        usage = self._usage_dict(getattr(resp, "usage", None))
        parsed: dict[str, Any] | None = None
        if schema is not None and text:
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                parsed = None
        return Completion(
            text=text, json=parsed, usage=usage, model=getattr(resp, "model", model)
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed(texts)

    def _resolve(self, role: str) -> str:
        try:
            return self._role_to_model[role]
        except KeyError as e:
            raise KeyError(f"No model configured for role {role!r}") from e

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        for attr in ("model_dump", "dict"):
            fn = getattr(usage, attr, None)
            if callable(fn):
                try:
                    return fn()
                except TypeError:
                    pass
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }


def build_openrouter_llm(settings: Any) -> OpenRouterLLM:
    """Composition helper: build an OpenRouterLLM from a Settings instance."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key or "missing",
        base_url=settings.openrouter_base_url,
        default_headers={
            "HTTP-Referer": getattr(settings, "app_referer", ""),
            "X-Title": getattr(settings, "app_title", "Engram"),
        },
    )
    role_to_model = {
        "tutor": settings.model_for("tutor"),
        "extractor": settings.model_for("extractor"),
        "reflector": settings.model_for("reflector"),
        "embedder": settings.model_for("embedder"),
    }
    return OpenRouterLLM(
        client=client, role_to_model=role_to_model, embedder=build_embedder(settings)
    )


# Back-compat alias used by the composition root.
build_llm = build_openrouter_llm
