"""Generate a whiteboard SVG panel from a natural-language intent.

One LLM call (role "diagram", a GLM model on DashScope) returns a self-contained
SVG diagram whose labelled parts carry `data-clicky="src-<name>"` anchors. The
client sandboxes the SVG in an opaque-origin iframe and a trusted bridge reports
each anchor's rect back so the clicky cursor can point at sub-parts.

The model is asked for a strict JSON object so we can pull out the caption, the
SVG markup, and the anchor names without brittle scraping. `json_object` mode is
requested via the adapter's `schema` arg (see OpenAICompatibleLLM.complete).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from engram.core.models import Message

# Role name — must match the entry wired into Settings.model_for and
# build_llm's roles tuple. Resolves to Settings.model_diagram (a GLM model).
DIAGRAM_ROLE = "diagram"

_SYSTEM = (
    "You are a whiteboard tutor that draws clear, minimal SVG diagrams to explain "
    "concepts. Respond with a SINGLE JSON object and nothing else, of the shape:\n"
    '{"caption": string, "svg": string, "anchors": string[]}\n\n'
    "Rules for the SVG:\n"
    "- A self-contained <svg> element with an explicit viewBox (e.g. "
    'viewBox="0 0 640 400"). No <script>, no external URLs, no <image>.\n'
    "- Use plain shapes and <text> labels. Keep it legible on a light background "
    "(dark strokes, few colours).\n"
    "- Give every labelled part a data-clicky anchor named 'src-<slug>' (e.g. "
    'data-clicky="src-nucleus"). Put the attribute on the <g>, shape, or <text> '
    "that visually IS that part, so a cursor pointing at it lands on the right place.\n"
    '- List every anchor name you used in "anchors".\n'
    "Keep the whole response under ~2500 tokens."
)

# Passed as the adapter's `schema` arg purely to flip on json_object mode; the
# prompt above is the real contract (the adapter does not enforce the shape).
_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "svg": {"type": "string"},
        "anchors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["svg"],
}

_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)
_CLICKY_RE = re.compile(r'data-clicky\s*=\s*"([^"]+)"', re.IGNORECASE)


class DiagramError(RuntimeError):
    """The model produced no usable SVG for this intent."""


@dataclass
class Panel:
    panel_id: str
    intent: str
    caption: str
    html: str
    anchors: list[str] = field(default_factory=list)
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "intent": self.intent,
            "caption": self.caption,
            "html": self.html,
            "anchors": self.anchors,
            "model": self.model,
            "usage": self.usage,
        }


def _extract_svg(text: str) -> tuple[str, str, list[str]]:
    """Pull (svg, caption, anchors) out of a model reply.

    Tries strict JSON first (what the prompt asks for); falls back to scraping a
    bare <svg> block if the model wrapped or malformed the JSON. Anchors are
    re-derived from the SVG's data-clicky attributes so they never disagree with
    what the client can actually resolve.
    """
    caption = ""
    svg = ""
    stripped = text.strip()
    # Tolerate ```json fences some models add despite the instruction.
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = re.sub(r"^json\s*", "", stripped, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            caption = str(obj.get("caption") or "")
            svg = str(obj.get("svg") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    if "<svg" not in svg:
        m = _SVG_RE.search(text)
        if m:
            svg = m.group(0)
    if "<svg" not in svg:
        raise DiagramError("model returned no <svg> markup")
    anchors = sorted(set(_CLICKY_RE.findall(svg)))
    return svg, caption, anchors


async def generate_panel(
    llm: Any, intent: str, anchors: dict[str, str] | None = None
) -> Panel:
    """Call the diagram LLM and assemble a Panel. Raises DiagramError on no SVG.

    `anchors` is an optional map of pre-declared `src-<slug>` ids the tutor
    intends to point at, each with a short description. When present it is
    appended to the prompt requiring GLM to stamp `data-clicky="<slug>"` on the
    matching element, so a `[point:src-slug]` gesture in the same reply resolves.
    """
    intent = (intent or "").strip()
    if not intent:
        raise DiagramError("empty intent")
    user = f"Draw a diagram to explain: {intent}"
    if anchors:
        lines = "\n".join(f'- data-clicky="{slug}" on: {desc}' for slug, desc in anchors.items())
        user += (
            "\n\nREQUIRED POINTING ANCHORS — attach these EXACT data-clicky ids "
            "to the element that draws each part:\n" + lines
        )
    messages = [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
    completion = await llm.complete(DIAGRAM_ROLE, messages, schema=_JSON_SCHEMA)
    svg, caption, found_anchors = _extract_svg(completion.text or "")
    return Panel(
        panel_id=uuid.uuid4().hex,
        intent=intent,
        caption=caption or intent,
        html=svg,
        anchors=found_anchors,
        model=completion.model,
        usage=completion.usage or {},
    )
