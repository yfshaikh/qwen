"""Unit tests use a fake OpenAI-compatible client + a local embedder. The live
test runs only when `OPENROUTER_API_KEY` is in the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.llm.openrouter import OpenRouterLLM
from engram.core.models import Message


# ---------- fake chat client ----------
@dataclass
class _Msg:
    content: str


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Usage:
    prompt_tokens: int = 1
    completion_tokens: int = 2
    total_tokens: int = 3


@dataclass
class _ChatCompletion:
    choices: list
    usage: _Usage
    model: str


class _FakeCompletions:
    def __init__(self, content: str = "hello from fake") -> None:
        self.calls: list[dict] = []
        self.content = content

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _ChatCompletion(
            choices=[_Choice(message=_Msg(content=self.content))],
            usage=_Usage(),
            model=kwargs["model"],
        )


class _FakeChat:
    def __init__(self, content: str = "hello from fake") -> None:
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content: str = "hello from fake") -> None:
        self.chat = _FakeChat(content)


# ---------- tests ----------
async def test_complete_uses_role_to_model_map():
    client = _FakeClient()
    llm = OpenRouterLLM(client, {"tutor": "tutor-x"}, HashingEmbedder(8))

    result = await llm.complete("tutor", [Message(role="user", content="hi")])

    assert result.text == "hello from fake"
    assert result.model == "tutor-x"
    assert result.usage["total_tokens"] == 3
    sent = client.chat.completions.calls[0]
    assert sent["model"] == "tutor-x"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "response_format" not in sent


async def test_complete_with_schema_sets_json_and_parses():
    client = _FakeClient(content='{"x": "y"}')
    llm = OpenRouterLLM(client, {"extractor": "ext-x"}, HashingEmbedder(8))

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    result = await llm.complete("extractor", [Message(role="user", content="...")], schema=schema)

    sent = client.chat.completions.calls[0]
    assert sent["response_format"] == {"type": "json_object"}
    assert result.json == {"x": "y"}


async def test_unknown_role_raises():
    llm = OpenRouterLLM(_FakeClient(), {"tutor": "t"}, HashingEmbedder(8))
    with pytest.raises(KeyError):
        await llm.complete("nope", [Message(role="user", content="x")])


async def test_embed_delegates_to_embedder():
    llm = OpenRouterLLM(_FakeClient(), {"embedder": "e"}, HashingEmbedder(16))
    vecs = await llm.embed(["alpha beta", "alpha beta"])
    assert len(vecs) == 2 and len(vecs[0]) == 16
    assert vecs[0] == vecs[1]  # deterministic


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set — live OpenRouter test skipped",
)
async def test_live_openrouter_completion():
    from engram.adapters.llm.openrouter import build_openrouter_llm
    from engram.app.config import Settings

    llm = build_openrouter_llm(Settings())
    r = await llm.complete("tutor", [Message(role="user", content="Say 'pong'.")])
    assert r.text and "pong" in r.text.lower()
