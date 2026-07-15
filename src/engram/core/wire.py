"""Single source of truth for the HTTP wire shapes.

**Shape rule** (WS-4a/4b): a domain value has at most three representations,
each with one owner —

- **dataclass** in `core.models` — the in-process domain object (`Node`,
  `Edge`, `Evidence`, ...).
- **TypedDict** in `core.models` — the typed shape of a storage *read*
  return (`GraphNode`, `GraphEdge`, `AuditRow`, `ScoredNode`, ...); still a
  plain `dict` at runtime, only checkers see the keys.
- **Pydantic**, defined **here** in `core.wire` — the actual HTTP wire
  model, used for request validation and response serialization. `app`'s
  `/graph`, `/audit`, `/recall` handlers and `integrations.fastapi`'s
  `memory_router` both import these; neither module defines its own copy.

`GraphNode`/`GraphEdge`/`AuditRow` intentionally share field names/shapes
with their `core.models` TypedDict namesakes — that mirroring IS the
contract between "what storage hands back" and "what goes over the wire".
If one shape changes, update both and re-check `tests/test_wire_golden.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GraphEvidence(BaseModel):
    kind: str
    content: str | None = None
    importance: float | None = None


class GraphNode(BaseModel):
    id: str | None = None  # source (core.models.GraphNode / node.id) permits None;
    label: str             # required here would 500 /graph past the router's try/except
    type: str
    summary: str | None = None
    mastery: float | None = None
    confidence: float | None = None
    salience: float | None = None
    importance: float | None = None
    evidence: list[GraphEvidence] = Field(default_factory=list)


class GraphEdge(BaseModel):
    id: str | None = None
    source: str
    target: str
    type: str
    weight: float


class AuditRow(BaseModel):
    id: str
    op: str
    rationale: str | None = None
    model: str | None = None
    tokens: int | None = None
    cost: float | None = None
    ts: datetime | None = None  # facade passes storage's ts through untyped; a
    # non-datetime must not 500 /audit past the handler (matches GraphNode.id)
