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
    @property
    def chat(self) -> Any: ...


class OpenAICompatibleLLM:
    """Implements core.ports.LLMPort against any OpenAI-compatible chat API."""

    def __init__(self, client: _AsyncChatClient, role_to_model: dict[str, str],
                 role_to_temperature: dict[str, float] | None = None) -> None:
        self._client = client
        self._role_to_model = role_to_model
        # Absent role -> omit `temperature` entirely and take the provider
        # default. Not the same as passing 0.0, and not the same as passing 1.0 —
        # providers differ on their default, so we don't guess one.
        self._role_to_temperature = role_to_temperature or {}

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
        temperature = self._role_to_temperature.get(role)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if schema is not None:
            # OpenAI-compatible json_object mode; the prompt itself must describe
            # the schema for the model. (Structured parsing lands in Phase 2.)
            kwargs["response_format"] = {"type": "json_object"}
        if role == "reflector":
            # The reflector prompt demands a single "yes"/"no" token (see
            # keeper.py:_reflector_confirm), so a small cap is safe. Every other
            # role is left at the provider default — capping extractor/tutor/
            # student/judge output risks truncating a full JSON graph or a
            # transcript, which is NOT safe (see Task A6 scope note).
            #
            # MEASURED NO-OP on the current stack: eval run 27b8c5a7 recorded
            # 1773 reflector completion_tokens under this cap (~90-160/call over
            # 11 confirmed merges). qwen3.7-max is a thinking model — this bounds
            # only the visible answer ("yes" fits), while thinking tokens bill
            # unclamped. Kept because it costs nothing and does clamp providers
            # that cap total output; do NOT cite it as a live token saving. The
            # reflector's real spend is thinking tokens — batching the confirms
            # (Phase C) is what would move that number.
            kwargs["max_tokens"] = 4

        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content if resp.choices else None
        usage = self._usage_dict(getattr(resp, "usage", None))
        return Completion(text=text, usage=usage, model=getattr(resp, "model", model))

    async def stream(self, role: str, messages: list[Message]) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": self._resolve(role),
            "messages": [asdict(m) for m in messages],
            "stream": True,
        }
        temperature = self._role_to_temperature.get(role)
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.chat.completions.create(**kwargs)
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
    roles = ("tutor", "extractor", "reflector", "student", "judge")
    role_to_model = {r: settings.model_for(r) for r in roles}
    # Only roles with a configured temperature land in the map; the rest keep the
    # provider default (see OpenAICompatibleLLM.__init__).
    role_to_temperature = {
        r: t for r in roles if (t := settings.temperature_for(r)) is not None
    }
    return OpenAICompatibleLLM(client=client, role_to_model=role_to_model,
                               role_to_temperature=role_to_temperature)
