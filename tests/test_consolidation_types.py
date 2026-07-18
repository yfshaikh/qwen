from engram.core.consolidation import (
    AuditEntry,
    ConsolidationPlan,
    ConsolidationReport,
    MasteryPoint,
)


def test_plan_defaults_are_empty():
    p = ConsolidationPlan(learner_id="a")
    assert p.new_nodes == []
    assert p.node_updates == []
    assert p.new_edges == []
    assert p.new_evidence == []
    assert p.mastery_history == []
    assert p.audit == []
    assert p.processed_event_ids == []


def test_report_defaults():
    r = ConsolidationReport(learner_id="a")
    assert r.processed_events == 0
    assert r.nodes_created == 0
    assert r.skipped is False
    assert r.errors == []


def test_audit_and_mastery_point():
    a = AuditEntry(op="link", rationale="why")
    assert a.op == "link" and a.model is None
    mp = MasteryPoint(node_id="n1", mastery=0.5, confidence=0.3)
    assert mp.node_id == "n1"
