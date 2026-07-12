"""The `engram` top level is the stable consumer API: everything in __all__
imports, py.typed ships, and the pydantic HTTP models stay field-compatible
with the exported TypedDicts (drift guard for known-drift #marfini)."""
from pathlib import Path

import engram


def test_all_exports_importable():
    assert engram.__version__ == "0.1.0"
    for name in engram.__all__:
        assert getattr(engram, name) is not None, name
    for required in ("Engram", "EngramHost", "DisabledEngram", "LearningEvent",
                     "RecallResult", "Subgraph", "ScoredNode", "GraphView",
                     "GraphNode", "AuditRow", "ConsolidationReport", "NodeType",
                     "EdgeType", "EvidenceKind"):
        assert required in engram.__all__, required


def test_py_typed_ships():
    assert (Path(engram.__file__).parent / "py.typed").exists()


def test_pydantic_schema_covers_typeddict_fields():
    # app/schemas.py must never drift behind the exported shapes again
    from engram.app import schemas
    from engram.core import models

    assert set(models.GraphNode.__annotations__) <= (
        set(schemas.GraphNode.model_fields) | {"evidence"})
    assert set(models.AuditRow.__annotations__) == set(schemas.AuditRow.model_fields)
