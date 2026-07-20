"""Pipeline: inline draw/gesture tags drive whiteboard renders + clicky events,
with gesture emit ordered just before its sentence's audio, and tags stripped
from the spoken/returned text.
"""

from engram.core.engram import Engram
from engram.core.models import Completion
from engram.voice.pipeline import VoicePipeline
from tests.fakes import FakeEmbedder, FakeStorage

_SVG = '<svg viewBox="0 0 10 10"><g data-clicky="src-gate"/></svg>'


class _TagLLM:
    """Streams `chunks` for the tutor role; returns an SVG for the diagram role."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.complete_calls: list[tuple] = []

    async def complete(self, role, messages, schema=None):
        self.complete_calls.append((role, messages, schema))
        return Completion(text=_SVG, usage={"total_tokens": 1}, model="glm-4.6")

    async def stream(self, role, messages):
        for c in self.chunks:
            yield c


class _OrderedRecorder:
    """Records text messages and audio bytes in one ordered log."""

    def __init__(self):
        self.log: list[tuple[str, object]] = []

    async def send_text(self, msg):
        self.log.append(("text", msg))

    async def send_bytes(self, b):
        self.log.append(("audio", b))

    def types(self):
        return [m["type"] for k, m in self.log if k == "text"]

    def kinds_order(self):
        # Flatten to a sequence of tags for ordering assertions.
        out = []
        for kind, payload in self.log:
            if kind == "audio":
                out.append(("audio", None))
            else:
                out.append((payload["type"], payload.get("anchor") or payload.get("intent")))
        return out


def _pipeline(chunks):
    eng = Engram(storage=FakeStorage(), llm=_TagLLM(chunks), embedder=FakeEmbedder(dim=1024))

    async def fake_transcribe(audio, mime, *, api_key, model, language=None):
        return "how does an nmos work"

    async def fake_stream_speech(text, *, api_key, model, voice="Cherry"):
        yield b"WAV"

    return eng, VoicePipeline(eng, api_key="K", stt_model="m", tts_model="m",
                              transcribe=fake_transcribe, stream_speech=fake_stream_speech)


# A reply that draws (tag split across chunks), then points at two parts in two
# separate sentences.
_CHUNKS = [
    "[draw: nmos transistor | src-gate=the metal gate; src-cha",
    "nnel=the channel] The gate [poi",
    "nt:src-gate] sits on top of the oxide. ",
    "The channel [circle:src-channel] forms below.",
]


async def test_draw_tag_triggers_render_and_pending_before_audio():
    eng, pipe = _pipeline(_CHUNKS)
    rec = _OrderedRecorder()
    await pipe.run_turn(b"A", "audio/webm", "a", [], rec.send_text, rec.send_bytes)

    order = rec.kinds_order()
    types = [t for t, _ in order]
    assert "whiteboard_pending" in types
    assert "whiteboard_panel" in types
    # The render was routed to the diagram role with the declared anchors.
    role, messages, _ = eng.llm.complete_calls[0]
    assert role == "diagram"
    assert "src-gate" in messages[-1].content and "src-channel" in messages[-1].content
    # whiteboard_pending precedes the first audio (loader shows while drawing).
    first_audio = next(i for i, (t, _) in enumerate(order) if t == "audio")
    first_pending = next(i for i, (t, _) in enumerate(order) if t == "whiteboard_pending")
    assert first_pending < first_audio


async def test_gestures_emit_just_before_their_sentence_audio():
    _, pipe = _pipeline(_CHUNKS)
    rec = _OrderedRecorder()
    await pipe.run_turn(b"A", "audio/webm", "a", [], rec.send_text, rec.send_bytes)

    order = rec.kinds_order()
    audio_idx = [i for i, (t, _) in enumerate(order) if t == "audio"]
    gate_idx = next(i for i, (t, a) in enumerate(order) if t == "clicky_gesture" and a == "src-gate")
    chan_idx = next(i for i, (t, a) in enumerate(order) if t == "clicky_gesture" and a == "src-channel")

    # src-gate fires before sentence 1's audio; src-channel before sentence 2's
    # audio but AFTER sentence 1's audio (a later sentence's tag must wait).
    assert gate_idx < audio_idx[0]
    assert audio_idx[0] < chan_idx < audio_idx[1]


async def test_tags_are_stripped_from_tokens_and_reply():
    _, pipe = _pipeline(_CHUNKS)
    rec = _OrderedRecorder()
    _, reply = await pipe.run_turn(b"A", "audio/webm", "a", [], rec.send_text, rec.send_bytes)

    token_text = "".join(m["text"] for k, m in rec.log
                         if k == "text" and m["type"] == "token")
    assert "[" not in token_text and "draw:" not in token_text and "point:" not in token_text
    assert "[" not in reply and "src-gate" not in reply
    assert "gate" in reply and "channel" in reply
    # The clicky_gesture events themselves carry the anchors.
    anchors = [m["anchor"] for k, m in rec.log
               if k == "text" and m["type"] == "clicky_gesture"]
    assert anchors == ["src-gate", "src-channel"]


async def test_turn_still_completes_with_turn_done_last():
    _, pipe = _pipeline(_CHUNKS)
    rec = _OrderedRecorder()
    await pipe.run_turn(b"A", "audio/webm", "a", [], rec.send_text, rec.send_bytes)
    assert rec.types()[-1] == "turn_done"
