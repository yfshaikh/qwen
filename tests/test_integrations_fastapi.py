"""memory_router: auth-injectable observability surface (E5)."""
import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from engram.core.engram import Engram
from engram.core.models import Node, NodeType
from engram.runtime.host import EngramHost
from engram.integrations.fastapi import memory_router
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


async def _host(started=True):
    host = EngramHost(Engram(storage=FakeStorage(), llm=FakeLLM(),
                             embedder=FakeEmbedder(dim=8)))
    if started:
        await host.start()
    return host


def _app(host, admin=True):
    app = FastAPI()

    async def learner_id_dep() -> str:
        return "user-1"

    async def admin_dep() -> str:
        return "admin"

    app.include_router(memory_router(
        lambda: host, learner_id_dep=learner_id_dep,
        admin_dep=admin_dep if admin else None))
    return app


def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_graph_scoped_to_dep_learner():
    host = await _host()
    await host.memory.storage.insert_node(Node(
        learner_id="user-1", type=NodeType.CONCEPT, label="Mine"))
    await host.memory.storage.insert_node(Node(
        learner_id="user-2", type=NodeType.CONCEPT, label="Theirs"))
    async with _client(_app(host)) as c:
        r = await c.get("/memory/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert [n["label"] for n in body["nodes"]] == ["Mine"]  # E5: no cross-read


async def test_status_reflects_is_consolidating():
    host = await _host()
    async with _client(_app(host)) as c:
        assert (await c.get("/memory/status")).json() == {"consolidating": False}


async def test_disabled_host_returns_enabled_false_http_200():
    host = await _host(started=False)   # never started -> DisabledEngram
    async with _client(_app(host)) as c:
        r = await c.get("/memory/graph")
        assert r.status_code == 200 and r.json()["enabled"] is False
        rp = await c.post("/memory/admin/recall-probe",
                          json={"learner_id": "x", "query": "q"})
        assert rp.status_code == 200 and rp.json()["enabled"] is False


async def test_admin_routes_absent_without_admin_dep():
    host = await _host()
    async with _client(_app(host, admin=False)) as c:
        assert (await c.get("/memory/admin/health")).status_code == 404
        assert (await c.get("/memory/graph")).status_code == 200  # self stays


async def test_admin_audit_serializes_ts():
    from engram.core.consolidation import AuditEntry, ConsolidationPlan
    host = await _host()
    await host.memory.storage.apply_consolidation(ConsolidationPlan(
        learner_id="L", audit=[AuditEntry(op="merge", rationale="r")]))
    async with _client(_app(host)) as c:
        r = await c.get("/memory/admin/audit", params={"learner_id": "L"})
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert row["op"] == "merge" and isinstance(row["ts"], str)  # isoformat


async def test_engram_failure_mid_request_is_enabled_false(caplog):
    host = await _host()

    async def boom(learner_id, focus=None):
        raise RuntimeError("db gone")

    host.memory.graph = boom  # type: ignore[method-assign]
    async with _client(_app(host)) as c:
        r = await c.get("/memory/graph")
    assert r.status_code == 200 and r.json()["enabled"] is False
