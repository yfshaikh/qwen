"""Inline gesture + draw tags — how the tutor drives its whiteboard and pointer.

The LLM embeds tags directly in its reply text, exactly where it means them:

- ``[draw: cross-section of an NMOS transistor | src-gate=the metal gate; src-channel=the channel]``
  — asks the whiteboard to render an SVG diagram of *intent*, pre-declaring the
  ``src-*`` anchors it will point at (each ``slug=description`` biases the
  generator to stamp ``data-clicky="slug"`` on the right element).
- ``[point:src-gate]`` / ``[circle:panel-current:the whole thing]`` /
  ``[show:panel-2]`` — move the on-screen cursor to an anchor (or, for ``show``,
  switch the board to an earlier panel).

The pipeline strips every complete tag from the spoken/displayed text and turns
it into a WS event, so both cost zero extra LLM rounds (unlike a tool-call).

``GestureTagParser`` is stream-safe: tokens arrive in arbitrary splits, so a tag
may span chunks. Text is only held back while a trailing fragment could still
become a tag; anything else passes through untouched. Ported from Marfini's
``api/voice_tutor/clicky/tags.py`` and extended with the ``draw`` verb (the qwen
voice loop is a plain streaming completion — no tool-calling — so the render
trigger is an inline tag too).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Cursor-drawing gestures. `show` rides the same channel but switches the board
# instead of drawing; `draw` triggers a whiteboard render (handled separately by
# the pipeline, which kicks off generation the moment the tag is parsed).
_GESTURES = ("point", "circle", "underline", "arrow")
_VERBS = _GESTURES + ("show", "draw")

# panel-current / panel-N target the parent DOM (the board canvas / filmstrip);
# src-<slug> targets a [data-clicky] element *inside* a rendered panel iframe
# (resolved client-side via the panel bridge). The console has no lesson
# sections, so those Marfini anchor families are dropped.
_ANCHOR_RE = re.compile(r"^(panel-current|panel-\d+|src-[a-z0-9-]{1,40})$")
_SRC_RE = re.compile(r"^src-[a-z0-9-]{1,40}$")

# Any tag-shaped span, valid or not — matched tags are ALWAYS removed from the
# text (a malformed anchor must never be spoken aloud). The body cap is generous
# so a draw tag's intent + anchor declarations fit.
_TAG_RE = re.compile(r"\[(" + "|".join(_VERBS) + r"):([^\]\n]{1,400})\]")

# A trailing '[' fragment longer than this can't be a tag — release it. Larger
# than Marfini's (128) to cover the longer draw body.
_MAX_TAG_LEN = 512


def _could_become_tag(fragment: str) -> bool:
    """Could an unclosed ``[...`` fragment still grow into a real tag?"""
    body = fragment[1:]
    if ":" in body:
        return body.split(":", 1)[0] in _VERBS
    return any(g.startswith(body) for g in _VERBS) if body else True


def _parse_draw(body: str) -> dict:
    """Parse a draw body ``<intent> | slug=desc; slug2=desc2`` into an event.

    The anchor map is optional. Only ``src-<slug>`` keys are kept; a malformed
    declaration is dropped (never fatal). Descriptions are trimmed to 80 chars.
    """
    intent_part, sep, anchor_part = body.partition("|")
    anchors: dict[str, str] = {}
    if sep:
        for decl in anchor_part.split(";"):
            slug, eq, desc = decl.partition("=")
            slug = slug.strip()
            if eq and _SRC_RE.match(slug):
                anchors[slug] = desc.strip()[:80]
    return {"kind": "draw", "intent": intent_part.strip(), "anchors": anchors}


class GestureTagParser:
    """Incremental tag extractor: ``feed(chunk) -> (clean_text, events)``.

    Each event is a dict with a ``kind`` of ``"gesture"`` or ``"draw"`` plus an
    ``_at`` character offset into the cleaned output (used by the pipeline to
    fire a gesture only once the text up to that point has been handed to TTS).
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> tuple[str, list[dict]]:
        self._buf += chunk
        events: list[dict] = []
        removed = 0  # chars deleted by tags handled so far this call

        def _consume(m: re.Match) -> str:
            nonlocal removed
            verb, body = m.group(1), m.group(2)
            at = m.start() - removed
            removed += len(m.group(0))
            if verb == "draw":
                ev = _parse_draw(body)
                ev["_at"] = at
                events.append(ev)
                return ""
            anchor, _, note = body.partition(":")  # note optional
            anchor = anchor.strip()
            if _ANCHOR_RE.match(anchor):
                events.append({
                    "kind": "gesture",
                    "gesture": verb,
                    "anchor": anchor,
                    "note": note.strip()[:40],
                    "_at": at,
                })
            else:
                logger.warning("Dropping gesture tag with invalid anchor: %r", m.group(0))
            return ""

        text = _TAG_RE.sub(_consume, self._buf)

        # The tail may hold the START of a tag whose ']' hasn't streamed in yet.
        cut = len(text)
        li = text.rfind("[")
        if (
            li != -1
            and "]" not in text[li:]
            and len(text) - li < _MAX_TAG_LEN
            and _could_become_tag(text[li:])
        ):
            cut = li
        out, self._buf = text[:cut], text[cut:]
        return out, events

    def flush(self) -> str:
        """Release any held fragment (stream ended; it never became a tag)."""
        out, self._buf = self._buf, ""
        return out
