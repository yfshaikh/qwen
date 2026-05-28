"""Protocols are structural — these tests assert our fakes satisfy them and that
the surface listed in the spec is present."""

from engram.core.ports import HostPort, LLMPort, StoragePort
from tests.fakes import FakeLLM, FakeStorage


def test_fake_storage_satisfies_storage_port():
    s: StoragePort = FakeStorage()  # mypy/runtime structural check
    assert hasattr(s, "health")
    assert hasattr(s, "insert_event")
    assert hasattr(s, "vector_search")


def test_fake_llm_satisfies_llm_port():
    llm: LLMPort = FakeLLM()
    assert hasattr(llm, "complete")
    assert hasattr(llm, "embed")


def test_host_port_surface_listed():
    # Sketch-only in Phase 0; assert the methods are declared on the Protocol.
    for name in ("ingest", "recall", "consolidate", "graph"):
        assert hasattr(HostPort, name), f"HostPort missing {name}"
