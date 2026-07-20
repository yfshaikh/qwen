"""Whiteboard SVG-diagram generation: adapter role wiring, the generate helper,
and the /whiteboard/panels route.

The diagram model is a GLM model on the SAME DashScope client (role "diagram"),
so the wiring tests below pin that a "diagram" role resolves and that build_llm
includes it — the seam that would silently break if the roles tuple or the
model_for table drifted.
"""

import httpx
import pytest
from httpx import ASGITransport

from engram.app.config import Settings
from engram.app.deps import get_engram
from engram.app.main import app
from engram.core.engram import Engram
from engram.core.models import Completion, Message
from engram.whiteboard.generate import DiagramError, generate_panel
from tests.fakes import FakeEmbedder, FakeStorage

_SVG = (
    '{"caption": "A neuron", "svg": "<svg viewBox=\\"0 0 100 100\\">'
    '<g data-clicky=\\"src-nucleus\\"><circle cx=\\"50\\" cy=\\"50\\" r=\\"10\\"/>'
    '<text data-clicky=\\"src-axon\\">axon</text></g></svg>", '
    '"anchors": ["src-nucleus", "src-axon"]}'
)


class _DiagramLLM:
    """Records the role/schema it was called with and returns canned text."""

    def __init__(self, text: str, model: str = "glm-5.2") -> None:
        self.text = text
        self.model = model
        self.calls: list[tuple[str, list[Message], object]] = []

    async def complete(self, role, messages, schema=None):
        self.calls.append((role, messages, schema))
        return Completion(text=self.text, usage={"total_tokens": 42}, model=self.model)

    async def stream(self, role, messages):  # pragma: no cover - unused here
        yield ""


# ---- config / adapter wiring -------------------------------------------------

def test_settings_model_for_diagram_defaults_to_glm(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    s = Settings(_env_file=None)
    assert s.model_for("diagram") == "glm-5.2"


def test_settings_model_diagram_env_override(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("ENGRAM_MODEL_DIAGRAM", "qwen-plus")
    s = Settings(_env_file=None)
    assert s.model_for("diagram") == "qwen-plus"


def test_build_llm_includes_diagram_role(monkeypatch):
    from engram.adapters.llm.openai_compatible import build_llm

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("ENGRAM_MODEL_DIAGRAM", "glm-test")
    llm = build_llm(Settings(_env_file=None))
    assert llm._role_to_model["diagram"] == "glm-test"


# ---- generate helper ---------------------------------------------------------

async def test_generate_panel_parses_json_and_derives_anchors():
    llm = _DiagramLLM(_SVG)
    panel = await generate_panel(llm, "how a neuron works")
    role, messages, schema = llm.calls[0]
    assert role == "diagram"           # routed to the GLM role
    assert schema is not None          # json_object mode requested
    assert panel.caption == "A neuron"
    assert "<svg" in panel.html
    # Anchors are re-derived from the SVG's data-clicky attributes, sorted.
    assert panel.anchors == ["src-axon", "src-nucleus"]
    assert panel.model == "glm-5.2"


async def test_generate_panel_scrapes_bare_svg_without_json():
    llm = _DiagramLLM('<svg viewBox="0 0 10 10"><rect data-clicky="src-box"/></svg>')
    panel = await generate_panel(llm, "a box")
    assert "<svg" in panel.html
    assert panel.anchors == ["src-box"]
    assert panel.caption == "a box"  # falls back to the intent


async def test_generate_panel_raises_without_svg():
    llm = _DiagramLLM("I cannot draw that.")
    with pytest.raises(DiagramError):
        await generate_panel(llm, "something")


async def test_generate_panel_rejects_empty_intent():
    with pytest.raises(DiagramError):
        await generate_panel(_DiagramLLM(_SVG), "   ")


# ---- route -------------------------------------------------------------------

@pytest.fixture
def eng_with_llm():
    e = Engram(storage=FakeStorage(), llm=_DiagramLLM(_SVG), embedder=FakeEmbedder(dim=1024))
    app.dependency_overrides[get_engram] = lambda: e
    yield e
    app.dependency_overrides.clear()


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_panels_route_returns_panel(eng_with_llm):
    async with _client() as c:
        r = await c.post("/whiteboard/panels", json={"intent": "how a neuron works"})
    assert r.status_code == 200
    body = r.json()
    assert body["panel_id"]
    assert "<svg" in body["html"]
    assert body["anchors"] == ["src-axon", "src-nucleus"]
    assert body["model"] == "glm-5.2"


async def test_panels_route_422_when_no_svg():
    e = Engram(storage=FakeStorage(), llm=_DiagramLLM("nope"), embedder=FakeEmbedder(dim=1024))
    app.dependency_overrides[get_engram] = lambda: e
    try:
        async with _client() as c:
            r = await c.post("/whiteboard/panels", json={"intent": "x"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


async def test_panels_route_validates_intent(eng_with_llm):
    async with _client() as c:
        r = await c.post("/whiteboard/panels", json={"intent": ""})
    assert r.status_code == 422
