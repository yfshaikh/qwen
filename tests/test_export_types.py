"""TS type generator: pydantic model_json_schema → TypeScript interfaces."""
from pathlib import Path

from engram.export_types import _type_of, emit_ts


def test_emit_contains_expected_shapes():
    out = emit_ts()
    assert "export interface MemGraphResponse" in out
    assert "enabled: boolean" in out
    assert "nodes: GraphNode[]" in out
    # MemAuditRow.ts is datetime | None → string | null
    assert "ts: string | null" in out


def test_default_cli_path_is_types_package(tmp_path, monkeypatch):
    """Canonical output lives in packages/engram-types (git-path npm package)."""
    from engram import export_types as et

    assert et._DEFAULT_OUT == Path("packages/engram-types/index.d.ts")
    # write into a temp tree via explicit argv (don't pollute cwd)
    out = tmp_path / "index.d.ts"
    et.main([str(out)])
    assert out.is_file() and "MemGraphResponse" in out.read_text()


def test_emit_is_deterministic():
    assert emit_ts() == emit_ts()


def test_array_of_anyof_wraps_union():
    # anyOf items must parenthesize before [] so TS precedence is correct
    schema = {
        "type": "array",
        "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }
    assert _type_of(schema, {}) == "(string | null)[]"