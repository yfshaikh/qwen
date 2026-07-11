
from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from engram.voice.pipeline import VoicePipeline
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _engram(canned="A limit is the value a function approaches. It is fundamental."):
    return Engram(storage=FakeStorage(), llm=FakeLLM(canned_text=canned),
                  embedder=FakeEmbedder(dim=1024))


class _Recorder:
    def __init__(self):
        self.texts, self.audio = [], []

    async def send_text(self, msg):
        self.texts.append(msg)

    async def send_bytes(self, b):
        self.audio.append(b)


def _pipeline(eng, *, stt_text="what are limits", tts_ok=True):
    async def fake_transcribe(audio, mime, *, api_key, model, language=None):
        return stt_text

    async def fake_stream_speech(text, *, api_key, model):
        if not tts_ok:
            raise RuntimeError("tts down")
        yield b"MP3"

    return VoicePipeline(eng, api_key="K", stt_model="m", tts_model="m",
                         transcribe=fake_transcribe, stream_speech=fake_stream_speech)


async def test_run_turn_event_order_and_return():
    eng = _engram()
    await eng.storage.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Limits",
             salience=0.9, embedding=[1.0] * 1024))
    rec = _Recorder()
    user_text, reply = await _pipeline(eng).run_turn(
        b"AUDIO", "audio/webm", "a", [], rec.send_text, rec.send_bytes)

    kinds = [m["type"] for m in rec.texts]
    assert kinds[0] == "status" and rec.texts[0]["phase"] == "transcribing"
    assert any(m["type"] == "transcript" and m["role"] == "user" for m in rec.texts)
    assert any(m["type"] == "token" for m in rec.texts)
    assert kinds[-1] == "turn_done"
    assert user_text == "what are limits"
    assert reply == "A limit is the value a function approaches. It is fundamental."
    assert rec.audio == [b"MP3", b"MP3"]  # one TTS call per completed sentence, streamed


async def test_run_turn_survives_tts_failure():
    eng = _engram()
    rec = _Recorder()
    user_text, reply = await _pipeline(eng, tts_ok=False).run_turn(
        b"AUDIO", "audio/webm", "a", [], rec.send_text, rec.send_bytes)
    assert reply  # reply still produced and returned
    assert any(m["type"] == "error" for m in rec.texts)  # error surfaced
    assert rec.texts[-1]["type"] == "turn_done"  # turn still completes


async def test_run_turn_empty_on_silence():
    eng = _engram()
    rec = _Recorder()
    user_text, reply = await _pipeline(eng, stt_text="").run_turn(
        b"", "audio/webm", "a", [], rec.send_text, rec.send_bytes)
    assert (user_text, reply) == ("", "")
    assert rec.texts[-1] == {"type": "status", "phase": "idle"}
