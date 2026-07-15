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


def _make(recorder, role_to_temperature=None):
    return OpenAICompatibleLLM(
        client=_FakeClient(recorder),
        role_to_model={
            "tutor": "qwen/tutor-model",
            "extractor": "qwen/extract-model",
            "reflector": "qwen/reflector-model",
        },
        role_to_temperature=role_to_temperature,
    )


async def test_complete_omits_temperature_when_unconfigured():
    """Omitted != 0.0 and != 1.0 — providers differ on their default, so an
    unconfigured role must take the provider's, not one we guessed."""
    rec = {}
    await _make(rec).complete("tutor", [Message(role="user", content="q")])
    assert "temperature" not in rec["kwargs"]


async def test_complete_sets_temperature_per_role():
    """The seam that lets a frozen-transcript eval pin the extractor to 0 without
    touching the production tutor — the reason docs/eval-harness.md #1 deferred
    pinning temperature at all."""
    rec = {}
    llm = _make(rec, {"extractor": 0.0})
    await llm.complete("extractor", [Message(role="user", content="q")])
    assert rec["kwargs"]["temperature"] == 0.0
    await llm.complete("tutor", [Message(role="user", content="q")])
    assert "temperature" not in rec["kwargs"]  # tutor untouched




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


async def test_complete_caps_max_tokens_for_reflector_only():
    rec = {}
    llm = _make(rec)
    await llm.complete("reflector", [Message(role="user", content="q")])
    assert rec["kwargs"]["max_tokens"] == 4


async def test_complete_does_not_cap_max_tokens_for_extractor():
    rec = {}
    llm = _make(rec)
    await llm.complete("extractor", [Message(role="user", content="q")])
    assert "max_tokens" not in rec["kwargs"]


async def test_complete_does_not_cap_max_tokens_for_tutor():
    rec = {}
    llm = _make(rec)
    await llm.complete("tutor", [Message(role="user", content="q")])
    assert "max_tokens" not in rec["kwargs"]


async def test_complete_unknown_role_raises():
    import pytest

    rec = {}
    llm = _make(rec)
    with pytest.raises(KeyError):
        await llm.complete("nope", [Message(role="user", content="q")])


class _StreamDelta:
    def __init__(self, content):
        self.content = content


class _StreamChoice:
    def __init__(self, content):
        self.delta = _StreamDelta(content)


class _StreamChunk:
    def __init__(self, content):
        self.choices = [_StreamChoice(content)]


class _StreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield _StreamChunk(c)


class _StreamCompletions:
    def __init__(self, rec):
        self._rec = rec

    async def create(self, **kwargs):
        self._rec["kwargs"] = kwargs
        return _StreamResponse(["A ", "limit ", None, "is..."])


class _StreamChat:
    def __init__(self, rec):
        self.completions = _StreamCompletions(rec)


class _StreamClient:
    def __init__(self, rec):
        self.chat = _StreamChat(rec)


async def test_stream_yields_text_deltas_and_skips_empty():
    rec = {}
    llm = OpenAICompatibleLLM(
        client=_StreamClient(rec), role_to_model={"tutor": "qwen/tutor-model"}
    )
    out = [d async for d in llm.stream("tutor", [Message(role="user", content="q")])]
    assert out == ["A ", "limit ", "is..."]  # None delta skipped
    assert rec["kwargs"]["stream"] is True
    assert rec["kwargs"]["model"] == "qwen/tutor-model"
    assert "temperature" not in rec["kwargs"]  # unconfigured -> provider default


async def test_stream_sets_temperature_per_role():
    rec = {}
    llm = OpenAICompatibleLLM(
        client=_StreamClient(rec), role_to_model={"tutor": "qwen/tutor-model"},
        role_to_temperature={"tutor": 0.0},
    )
    [d async for d in llm.stream("tutor", [Message(role="user", content="q")])]
    assert rec["kwargs"]["temperature"] == 0.0 and rec["kwargs"]["stream"] is True


# --- Groq json_validate_failed -> partial text ------------------------------
# Groq validates json_object output server-side and raises 400 with the bad text
# in `failed_generation`, where OpenAI returns it as a normal completion. The 400
# escaping complete() kills the whole run and skips Keeper._extract's repair
# prompt, which is built for exactly this. Real 5x eval run: 2 of 5 runs died here.

class _Boom(Exception):
    def __init__(self, body):
        super().__init__("400")
        self.body = body


def _raiser(body):
    class _C:
        async def create(self, **kwargs):
            raise _Boom(body)
    class _Chat:
        completions = _C()
    class _Client:
        chat = _Chat()
    return OpenAICompatibleLLM(client=_Client(), role_to_model={"extractor": "m"})


def _jvf(gen):
    return {"error": {"code": "json_validate_failed", "failed_generation": gen}}


async def test_json_validate_failed_returns_partial_text():
    llm = _raiser(_jvf('{"concepts":[{"label":"EM induc'))
    out = await llm.complete("extractor", [Message(role="user", content="q")])
    assert out.text == '{"concepts":[{"label":"EM induc'   # parser -> ExtractionError -> repair


async def test_json_validate_failed_with_empty_generation_returns_empty_not_none():
    """The reasoning-model case: Groq reports the failure with no text at all.
    Must still return a Completion so the repair prompt fires — a None here would
    read as 'no output' and could be mistaken for a successful empty extraction."""
    llm = _raiser(_jvf(""))
    out = await llm.complete("extractor", [Message(role="user", content="q")])
    assert out.text == ""


async def test_other_400s_still_raise():
    """Only json_validate_failed is recoverable. Swallowing e.g. a bad api key
    would turn a config error into a silently empty graph."""
    import pytest
    llm = _raiser({"error": {"code": "invalid_api_key", "message": "nope"}})
    with pytest.raises(_Boom):
        await llm.complete("extractor", [Message(role="user", content="q")])
