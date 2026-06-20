import uuid

from engram.adapters.storage.postgres import PostgresStorage
from engram.core.consolidation import AuditEntry, ConsolidationPlan


async def test_get_audit_orders_filters_and_limits(database_url):
    s = PostgresStorage(database_url)
    await s.connect()
    try:
        learner = f"t-{uuid.uuid4()}"
        await s.apply_consolidation(
            ConsolidationPlan(learner_id=learner, audit=[AuditEntry(op="extract", rationale="r1")])
        )
        await s.apply_consolidation(
            ConsolidationPlan(learner_id=learner, audit=[AuditEntry(op="link", rationale="r2")])
        )

        rows = await s.get_audit(learner)
        assert [r["op"] for r in rows] == ["extract", "link"]
        assert set(rows[0]) == {"id", "op", "rationale", "model", "tokens", "cost", "ts"}

        after = await s.get_audit(learner, since=rows[0]["ts"])
        assert [r["op"] for r in after] == ["link"]

        assert len(await s.get_audit(learner, limit=1)) == 1
    finally:
        await s.close()
