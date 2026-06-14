"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def database_url() -> str:
    # The compose db is the source of truth for tests; override via env if needed.
    return os.environ.get(
        "DATABASE_URL", "postgresql://engram:engram@localhost:5432/engram"
    )
