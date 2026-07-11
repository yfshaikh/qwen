"""TS type generator: pydantic model_json_schema → TypeScript interfaces."""
from engram.export_types import _type_of, emit_ts


def test_emit_contains_expected_shapes():
    out = emit_ts()
    assert "export interface MemGraphResponse" in out
    assert "enabled: boolean" in out
    assert "nodes: unknown[]" in out or "nodes:" in out  # unknown[] or better
    # MemAuditRow.ts is datetime | None → string | null
    assert "ts: string | null" in out


def test_emit_is_deterministic():
    assert emit_ts() == emit_ts()


def test_array_of_anyof_wraps_union():
    # anyOf items must parenthesize before [] so TS precedence is correct
    schema = {
        "type": "array",
        "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }
    assert _type_of(schema, {}) == "(string | null)[]"