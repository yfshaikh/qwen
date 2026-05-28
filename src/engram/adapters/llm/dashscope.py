"""DashScope LLMPort adapter — the file the submission's "uses Alibaba APIs"
link points at. Wraps the OpenAI SDK aimed at DashScope's OpenAI-compatible
endpoint (https://dashscope-intl.aliyuncs.com/compatible-mode/v1).

All Alibaba Cloud / Qwen calls in Engram flow through here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from engram.core.models import Completion, Message


class _AsyncOpenAILike(Protocol):
    chat: Any
    embeddings: Any


class DashScopeLLM:
    """Implements core.ports.LLMPort against DashScope's OpenAI-compatible API."""

    def __init__(
        self,
        client: _AsyncOpenAILike,
        role_to_model: dict[str, str],
    ) -> None:
        self._client = client
        self._role_to_model = role_to_model

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        model = self._resolve(role)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [asdict(m) for m in messages],
        }
        if schema is not None:
            # DashScope's OpenAI-compatible endpoint accepts json_object;
            # the prompt itself must describe the schema for the model.
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content if resp.choices else None
        usage = self._usage_dict(getattr(resp, "usage", None))
        return Completion(text=text, usage=usage, model=getattr(resp, "model", model))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._resolve("embedder")
        resp = await self._client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in resp.data]

    def _resolve(self, role: str) -> str:
        try:
            return self._role_to_model[role]
        except KeyError as e:
            raise KeyError(f"No model configured for role {role!r}") from e

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        # Works for both the SDK's pydantic model and our test fake.
        for attr in ("model_dump", "dict"):
            fn = getattr(usage, attr, None)
            if callable(fn):
                return fn()
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }


def build_dashscope_llm(settings: Any) -> DashScopeLLM:
    """Composition helper: build a DashScopeLLM from a Settings instance."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )
    role_to_model = {
        "tutor": settings.model_for("tutor"),
        "extractor": settings.model_for("extractor"),
        "reflector": settings.model_for("reflector"),
        "embedder": settings.model_for("embedder"),
    }
    return DashScopeLLM(client=client, role_to_model=role_to_model)
