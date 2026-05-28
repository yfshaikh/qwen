"""Unit tests use a fake OpenAI client (the SDK's surface is small). The live
test runs only when `DASHSCOPE_API_KEY` is in the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from engram.adapters.llm.dashscope import DashScopeLLM
from engram.core.models import Message


# ---------- fake OpenAI client ----------


@dataclass
class _FakeChoiceMsg:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeChoiceMsg


@dataclass
class _FakeUsage:
    prompt_tokens: int = 1
    completion_tokens: int = 2
    total_tokens: int = 3


@dataclass
class _FakeChatCompletion:
    choices: list[_FakeChoice]
    usage: _FakeUsage
    model: str


@dataclass
class _FakeEmbedItem:
    embedding: list[float]


@dataclass
class _FakeEmbedResp:
    data: list[_FakeEmbedItem]
    model: str
    usage: _FakeUsage


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeChatCompletion(
            choices=[_FakeChoice(message=_FakeChoiceMsg(content="hello from fake"))],
            usage=_FakeUsage(),
            model=kwargs["model"],
        )


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        n = len(kwargs["input"])
        return _FakeEmbedResp(
            data=[_FakeEmbedItem(embedding=[0.1] * 4) for _ in range(n)],
            model=kwargs["model"],
            usage=_FakeUsage(),
        )


class _FakeOpenAI:
    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.embeddings = _FakeEmbeddings()


# ---------- tests ----------


@pytest.mark.asyncio
async def test_complete_uses_role_to_model_map():
    role_to_model = {"tutor": "tutor-x", "extractor": "ext-x", "embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    result = await llm.complete("tutor", [Message(role="user", content="hi")])

    assert result.text == "hello from fake"
    assert result.model == "tutor-x"
    assert result.usage["total_tokens"] == 3
    sent = fake.chat.completions.calls[0]
    assert sent["model"] == "tutor-x"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "response_format" not in sent


@pytest.mark.asyncio
async def test_complete_passes_schema_as_json_response_format():
    role_to_model = {"extractor": "ext-x", "embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    await llm.complete("extractor", [Message(role="user", content="...")], schema=schema)

    sent = fake.chat.completions.calls[0]
    assert sent["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_embed_uses_embedder_model_and_batches():
    role_to_model = {"embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    vectors = await llm.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert vectors[0] == [0.1, 0.1, 0.1, 0.1]
    sent = fake.embeddings.calls[0]
    assert sent["model"] == "emb-x"
    assert sent["input"] == ["a", "b", "c"]


@pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY not set — live DashScope test skipped",
)
@pytest.mark.asyncio
async def test_live_dashscope_completion_and_embedding():
    """The proof beat for Phase 0a-local: when a real key is present, this hits
    DashScope's OpenAI-compatible endpoint and verifies both endpoints."""
    from engram.adapters.llm.dashscope import build_dashscope_llm
    from engram.app.config import Settings

    settings = Settings()  # reads .env
    llm = build_dashscope_llm(settings)

    r = await llm.complete("tutor", [Message(role="user", content="Say 'pong'.")])
    assert r.text and "pong" in r.text.lower()

    vectors = await llm.embed(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == settings.embedding_dim
