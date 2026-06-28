"""OpenAI-compatible chat adapter (implements core.ports.LLMPort).

Phase-0/MVP: pointed at OpenRouter (running Qwen models). The same class, given
a client built against DashScope's OpenAI-compatible endpoint, is the Alibaba
adapter later — see build_llm() and the spec's provider-seam section.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any, Protocol

from engram.core.models import Completion, Message


class _AsyncChatClient(Protocol):
    chat: Any


class OpenAICompatibleLLM:
    """Implements core.ports.LLMPort against any OpenAI-compatible chat API."""

    def __init__(self, client: _AsyncChatClient, role_to_model: dict[str, str]) -> None:
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
            # OpenAI-compatible json_object mode; the prompt itself must describe
            # the schema for the model. (Structured parsing lands in Phase 2.)
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content if resp.choices else None
        usage = self._usage_dict(getattr(resp, "usage", None))
        return Completion(text=text, usage=usage, model=getattr(resp, "model", model))

    async def stream(self, role: str, messages: list[Message]) -> AsyncIterator[str]:
        resp = await self._client.chat.completions.create(
            model=self._resolve(role),
            messages=[asdict(m) for m in messages],
            stream=True,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

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
                return fn()
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }


def build_llm(settings: Any) -> OpenAICompatibleLLM:
    """Composition helper: build the chat LLM (OpenRouter) from Settings."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )
    role_to_model = {
        "tutor": settings.model_for("tutor"),
        "extractor": settings.model_for("extractor"),
        "reflector": settings.model_for("reflector"),
        "student": settings.model_for("student"),
        "judge": settings.model_for("judge"),
    }
    return OpenAICompatibleLLM(client=client, role_to_model=role_to_model)
