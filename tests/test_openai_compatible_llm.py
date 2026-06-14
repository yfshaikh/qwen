from engram.adapters.llm.openai_compatible import OpenAICompatibleLLM
from engram.core.models import Message


class _FakeUsage:
    def model_dump(self):
        return {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content, model):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()
        self.model = model


class _FakeChatCompletions:
    def __init__(self, recorder):
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder["kwargs"] = kwargs
        return _FakeResponse("the answer", kwargs["model"])


class _FakeChat:
    def __init__(self, recorder):
        self.completions = _FakeChatCompletions(recorder)


class _FakeClient:
    def __init__(self, recorder):
        self.chat = _FakeChat(recorder)


def _make(recorder):
    return OpenAICompatibleLLM(
        client=_FakeClient(recorder),
        role_to_model={"tutor": "qwen/tutor-model", "extractor": "qwen/extract-model"},
    )


async def test_complete_resolves_role_to_model_and_passes_messages():
    rec = {}
    llm = _make(rec)
    out = await llm.complete("tutor", [Message(role="user", content="q")])
    assert out.text == "the answer"
    assert out.usage["total_tokens"] == 7
    assert rec["kwargs"]["model"] == "qwen/tutor-model"
    assert rec["kwargs"]["messages"] == [{"role": "user", "content": "q"}]
    assert "response_format" not in rec["kwargs"]


async def test_complete_with_schema_sets_json_response_format():
    rec = {}
    llm = _make(rec)
    await llm.complete("extractor", [Message(role="user", content="q")], schema={"x": 1})
    assert rec["kwargs"]["response_format"] == {"type": "json_object"}


async def test_complete_unknown_role_raises():
    import pytest

    rec = {}
    llm = _make(rec)
    with pytest.raises(KeyError):
        await llm.complete("nope", [Message(role="user", content="q")])
