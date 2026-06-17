"""Extraction — turn pending events into typed candidate nodes + relations.

The extractor LLM returns JSON; parse_extraction validates it into typed
candidates, dropping items with out-of-enum kinds/types but raising on
structurally broken JSON. Evidence may carry optional correct/mastery copied from
event signals (signal-greedy) — the planner prefers those over the kind table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engram.core.models import EdgeType, EvidenceKind, Message, NodeType

# Passed to LLMPort.complete as `schema` to trigger json_object mode; the prompt
# describes the shape for the model.
EXTRACTION_SCHEMA: dict = {"type": "object"}

_VALID_NODE_TYPES = {t.value for t in NodeType}
_VALID_KINDS = {k.value for k in EvidenceKind}
_VALID_REL_TYPES = {t.value for t in EdgeType}


class ExtractionError(Exception):
    """Raised when the extractor output is not usable JSON of the right shape."""


@dataclass(slots=True)
class ExtractedEvidence:
    kind: str
    content: str | None = None
    importance: float | None = None
    correct: bool | None = None
    mastery: float | None = None


@dataclass(slots=True)
class ExtractedNode:
    type: str
    label: str
    summary: str | None
    evidence: list[ExtractedEvidence] = field(default_factory=list)

    def embed_text(self) -> str:
        return self.label + (f" {self.summary}" if self.summary else "")


@dataclass(slots=True)
class ExtractedRelation:
    source_label: str
    target_label: str
    type: str


@dataclass(slots=True)
class Extraction:
    nodes: list[ExtractedNode] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


_SYSTEM = (
    "You extract a learner's knowledge graph from learning events. "
    "Return ONLY JSON with keys: concepts, preferences, goals (each a list of "
    '{label, summary, evidence:[{kind, content, importance, correct?, mastery?}]}) '
    "and relations (a list of {source_label, target_label, type}). "
    f"Evidence kind must be one of {sorted(_VALID_KINDS)}. "
    f"Relation type must be one of {sorted(_VALID_REL_TYPES)}. "
    "If an event's signals contain correct/mastery, copy them onto the evidence. "
    "Do not invent node types beyond concept/preference/goal."
)


def build_extraction_messages(events) -> list[Message]:
    lines = []
    for e in events:
        lines.append(
            json.dumps(
                {"type": e.type, "text": e.text, "refs": e.refs, "signals": e.signals}
            )
        )
    user = "Events:\n" + "\n".join(lines) + "\n\nReturn the JSON described above."
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]


def _evidence(raw: dict) -> ExtractedEvidence | None:
    kind = raw.get("kind")
    if kind not in _VALID_KINDS:
        return None
    return ExtractedEvidence(
        kind=kind,
        content=raw.get("content"),
        importance=raw.get("importance"),
        correct=raw.get("correct"),
        mastery=raw.get("mastery"),
    )


def parse_extraction(text: str) -> Extraction:
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ExtractionError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("top-level JSON is not an object")

    nodes: list[ExtractedNode] = []
    for key, node_type in (
        ("concepts", "concept"),
        ("preferences", "preference"),
        ("goals", "goal"),
    ):
        items = data.get(key, [])
        if not isinstance(items, list):
            raise ExtractionError(f"{key!r} is not a list")
        for it in items:
            if not isinstance(it, dict) or "label" not in it:
                continue
            if node_type not in _VALID_NODE_TYPES:
                continue
            evs = [_evidence(r) for r in it.get("evidence", []) if isinstance(r, dict)]
            nodes.append(
                ExtractedNode(
                    type=node_type,
                    label=str(it["label"]),
                    summary=it.get("summary"),
                    evidence=[e for e in evs if e is not None],
                )
            )

    relations: list[ExtractedRelation] = []
    rels = data.get("relations", [])
    if not isinstance(rels, list):
        raise ExtractionError("'relations' is not a list")
    for r in rels:
        if not isinstance(r, dict):
            continue
        if r.get("type") not in _VALID_REL_TYPES:
            continue
        if not r.get("source_label") or not r.get("target_label"):
            continue
        relations.append(
            ExtractedRelation(r["source_label"], r["target_label"], r["type"])
        )

    return Extraction(nodes=nodes, relations=relations)
