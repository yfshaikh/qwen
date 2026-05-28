# Engram Phase 0 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Engram repo with an app-agnostic core (3 ports), the pgvector schema, a DashScope `LLMPort` adapter, and a hello-world FastAPI app — fully runnable locally — so the only remaining work to satisfy the hackathon's "runs on Alibaba and calls DashScope" gate is the access-gated deploy in Phase 0b.

**Architecture:** Python 3.12 + FastAPI + asyncpg + pgvector. Dependencies point inward: `src/engram/core/` (pure domain — Protocols + dataclasses) is imported by `src/engram/adapters/` (Postgres + DashScope) and `src/engram/app/` (FastAPI + composition root); core imports none of them. Tests use in-process **fakes** that implement the same `Protocol`s; the live DashScope test auto-skips without an API key. The full DDL (`engram_nodes/edges/evidence/events/audit/mastery_history`) lands now; only `StoragePort.health()` has a real body — every other storage method `raise`s `NotImplementedError("Phase N")`.

**Tech Stack:** Python 3.12 · FastAPI · `uvicorn[standard]` · `openai` (pointed at DashScope) · `asyncpg` · `pgvector` · `pydantic` v2 · `pytest` · `pytest-asyncio` · `httpx` · Docker · Docker Compose · `pgvector/pgvector:pg16` image.

**Commit policy (user-specific):** the user's global rules forbid auto-commits. Every task ends at a **commit-ready checkpoint** with `git add` + a suggested message — the executor MUST stop and ask the user for explicit say-so before running `git commit`. Do not include `Co-Authored-By` trailers. Never read `.env`.

---

## File map

| Path | Responsibility |
|---|---|
| `LICENSE` | MIT, detectable by GitHub |
| `README.md` | What it is + how to run locally + pointer to 0b runbook |
| `.gitignore` | venv, `.env`, `__pycache__`, etc. |
| `.env.example` | All env vars, with placeholders only |
| `pyproject.toml` | Project metadata + runtime + `[dev]` deps |
| `docker-compose.yml` | `db` (pgvector/pg16) for local dev/tests; `app` added in Task 14 |
| `docker/Dockerfile` | App image for Phase 0b |
| `migrations/0001_engram_schema.sql` | Full schema from spec §6 |
| `src/engram/core/models.py` | Pure dataclasses + literals: `LearningEvent`, `Node`, `Edge`, `Evidence`, `Message`, `Completion`, `RecallResult`, `GraphView` |
| `src/engram/core/ports.py` | `Protocol`s: `LLMPort`, `StoragePort`, `HostPort` |
| `src/engram/adapters/storage/postgres.py` | `PostgresStorage` (`StoragePort`): real `health()`, others `raise NotImplementedError("Phase N")` |
| `src/engram/adapters/llm/dashscope.py` | `DashScopeLLM` (`LLMPort`) — **★ the "uses Alibaba APIs" proof file** |
| `src/engram/app/config.py` | env-loaded `Settings`: DB URL, DashScope base+key, role→model map |
| `src/engram/app/deps.py` | Composition root: builds adapters from settings; FastAPI dependency providers |
| `src/engram/app/main.py` | FastAPI app: `GET /health`, `POST /llm-ping` |
| `tests/conftest.py` | pytest config: event loop, DB fixture, settings overrides |
| `tests/fakes.py` | `FakeLLM`, `FakeStorage` implementing the Protocols |
| `tests/test_models.py` | Domain dataclass / enum smoke tests |
| `tests/test_ports_contract.py` | Protocols are satisfied by fakes; type checks |
| `tests/test_config.py` | `Settings` loading + role lookup |
| `tests/test_storage_postgres.py` | Live pgvector container: migration applies, vector round-trips, `health()` works |
| `tests/test_dashscope_adapter.py` | Mocked-client unit tests + live test gated on `DASHSCOPE_API_KEY` |
| `tests/test_app.py` | `httpx.AsyncClient` against the FastAPI app with fakes injected |
| `docs/deploy.md` | 0b runbook (account setup → RDS → ECS → live `/llm-ping`) |

---

## Task 1: Repo scaffolding, LICENSE, .gitignore, git init

**Files:**
- Create: `LICENSE`
- Create: `README.md`
- Create: `.gitignore`
- Create: `.env.example`
- Create: directory tree `src/engram/{core,adapters/{storage,llm},app}/__init__.py` and `tests/__init__.py`

- [ ] **Step 1: Initialize git**

```bash
cd /Users/yusufshaikh/Desktop/Projects/qwen
git init -b main
```

Expected: `Initialized empty Git repository in .../qwen/.git/`

- [ ] **Step 2: Write LICENSE (MIT)**

Create `LICENSE` with exact content:

```
MIT License

Copyright (c) 2026 Yusuf Shaikh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Write .gitignore**

Create `.gitignore`:

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/

# Env / secrets — NEVER commit
.env
.env.local
.env.*.local

# OS / editor
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 4: Write .env.example (placeholders only — no real values)**

Create `.env.example`:

```
# DashScope (Alibaba Model Studio) — OpenAI-compatible endpoint
DASHSCOPE_API_KEY=replace-me
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# Role -> model mapping (override per role)
ENGRAM_MODEL_TUTOR=qwen3-vl-plus
ENGRAM_MODEL_EXTRACTOR=qwen3.5-flash
ENGRAM_MODEL_REFLECTOR=qwen3-max
ENGRAM_MODEL_EMBEDDER=text-embedding-v4

# Embedding dimension — must match the migration's vector(N) columns
ENGRAM_EMBEDDING_DIM=1024

# Postgres
DATABASE_URL=postgresql://engram:engram@localhost:5432/engram
```

- [ ] **Step 5: Write README.md (skeleton — fleshed out in Task 15)**

Create `README.md`:

```markdown
# Engram

App-agnostic memory core for AI tutors. Submission to the Qwen Cloud Global AI Hackathon (Track 1: MemoryAgent).

See [`DESIGN.md`](./DESIGN.md) for the full architecture and [`docs/superpowers/specs/2026-05-27-engram-phase-0-foundations-design.md`](./docs/superpowers/specs/2026-05-27-engram-phase-0-foundations-design.md) for the Phase 0 spec.

This README is filled in by Task 15.
```

- [ ] **Step 6: Create the package tree (empty `__init__.py` files)**

```bash
mkdir -p src/engram/core src/engram/adapters/storage src/engram/adapters/llm src/engram/app tests migrations docker docs
touch src/engram/__init__.py src/engram/core/__init__.py \
      src/engram/adapters/__init__.py src/engram/adapters/storage/__init__.py \
      src/engram/adapters/llm/__init__.py src/engram/app/__init__.py \
      tests/__init__.py
```

- [ ] **Step 7: Sanity check**

```bash
ls LICENSE .gitignore .env.example README.md
find src tests migrations docker -type f -o -type d | head
```

Expected: all four root files exist; the package tree is present.

- [ ] **Step 8: Stop and ask the user to commit**

```bash
git add -A
git status
```

Suggested commit message (run only after explicit say-so):

```
chore: initialize repo with MIT LICENSE, gitignore, env example, package tree
```

---

## Task 2: pyproject.toml + dev install

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "engram"
version = "0.0.1"
description = "App-agnostic memory core for AI tutors."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Yusuf Shaikh" }]
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.7",
  "pydantic-settings>=2.4",
  "openai>=1.50",
  "asyncpg>=0.29",
  "pgvector>=0.3.6",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "ruff>=0.6",
]

[tool.hatch.build.targets.wheel]
packages = ["src/engram"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Create a venv and install**

```bash
cd /Users/yusufshaikh/Desktop/Projects/qwen
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Expected: `Successfully installed engram-0.0.1 ...` plus all deps.

- [ ] **Step 3: Verify the import works**

```bash
python -c "import engram; print('engram package importable')"
```

Expected: `engram package importable`

- [ ] **Step 4: Stop and ask the user to commit**

```bash
git add pyproject.toml
git status
```

Suggested message:

```
chore: add pyproject.toml with runtime and dev deps
```

---

## Task 3: Domain models (TDD)

**Files:**
- Create: `src/engram/core/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from datetime import datetime, timezone

from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    GraphView,
    LearningEvent,
    Message,
    Node,
    NodeType,
    RecallResult,
)


def test_learning_event_round_trip():
    e = LearningEvent(
        learner_id="alice",
        type="utterance",
        text="I don't get derivatives",
        refs={"doc_id": "calc-101", "page": 7},
        signals={"confusion": 0.8},
    )
    assert e.learner_id == "alice"
    assert e.refs["page"] == 7
    assert e.signals["confusion"] == 0.8
    assert isinstance(e.ts, datetime)
    assert e.ts.tzinfo is not None  # always tz-aware


def test_node_defaults_and_types():
    n = Node(learner_id="alice", type=NodeType.CONCEPT, label="derivatives")
    assert n.type is NodeType.CONCEPT
    assert n.mastery is None
    assert n.embedding is None
    assert n.source_refs == []
    assert n.forgotten_at is None


def test_edge_validates_type():
    edge = Edge(
        learner_id="alice",
        source_id="a",
        target_id="b",
        type=EdgeType.PREREQUISITE,
    )
    assert edge.type is EdgeType.PREREQUISITE


def test_evidence_kind_literal():
    ev = Evidence(node_id="n1", kind=EvidenceKind.QUIZ_WRONG, content="missed Q3")
    assert ev.kind is EvidenceKind.QUIZ_WRONG


def test_recall_and_graph_view_shapes():
    rv = RecallResult(text_block="...", subgraph={"nodes": [], "edges": []})
    assert rv.text_block == "..."
    gv = GraphView(nodes=[], edges=[])
    assert gv.nodes == [] and gv.edges == []


def test_message_shape():
    m = Message(role="user", content="hi")
    assert m.role == "user" and m.content == "hi"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.core.models'`

- [ ] **Step 3: Implement `src/engram/core/models.py`**

```python
"""Pure domain types. No I/O, no third-party imports beyond stdlib + dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NodeType(str, Enum):
    CONCEPT = "concept"
    PREFERENCE = "preference"
    GOAL = "goal"


class EdgeType(str, Enum):
    PREREQUISITE = "prerequisite"
    RELATES_TO = "relates_to"
    PART_OF = "part_of"


class EvidenceKind(str, Enum):
    EXPLAINED = "explained"
    ASKED_ABOUT = "asked_about"
    QUIZ_CORRECT = "quiz_correct"
    QUIZ_WRONG = "quiz_wrong"
    NOTE = "note"
    STRUGGLE = "struggle"
    DEMONSTRATED = "demonstrated"


@dataclass(slots=True)
class LearningEvent:
    learner_id: str
    type: str
    text: str | None = None
    refs: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Node:
    learner_id: str
    type: NodeType
    label: str
    id: str | None = None
    summary: str | None = None
    mastery: float | None = None
    confidence: float | None = None
    salience: float | None = None
    embedding: list[float] | None = None
    source_refs: list[Any] = field(default_factory=list)
    forgotten_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    last_seen_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Edge:
    learner_id: str
    source_id: str
    target_id: str
    type: EdgeType
    id: str | None = None
    weight: float = 1.0
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Evidence:
    node_id: str
    kind: EvidenceKind
    id: str | None = None
    content: str | None = None
    source_ref: dict[str, Any] | None = None
    embedding: list[float] | None = None
    importance: float | None = None
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass(slots=True)
class Completion:
    text: str | None = None
    json: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


@dataclass(slots=True)
class RecallResult:
    text_block: str
    subgraph: dict[str, Any]


@dataclass(slots=True)
class GraphView:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Stop and ask the user to commit**

```bash
git add src/engram/core/models.py tests/test_models.py
git status
```

Suggested message:

```
feat(core): domain dataclasses and bounded type enums
```

---

## Task 4: Core ports (Protocols) + smoke test

**Files:**
- Create: `src/engram/core/ports.py`
- Create: `tests/fakes.py`
- Test: `tests/test_ports_contract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ports_contract.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_ports_contract.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.core.ports'` (or `tests.fakes`).

- [ ] **Step 3: Implement `src/engram/core/ports.py`**

```python
"""The agnostic surface. Protocols only — no third-party imports, no bodies."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from engram.core.models import (
    Completion,
    GraphView,
    LearningEvent,
    Message,
    Node,
    RecallResult,
)


@runtime_checkable
class LLMPort(Protocol):
    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class StoragePort(Protocol):
    async def health(self) -> bool: ...

    # The remainder is the surface Phases 1–2 implement. Declared here so
    # adapters and fakes know what's coming and signatures stay stable.
    async def insert_event(self, e: LearningEvent) -> str: ...
    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]: ...


@runtime_checkable
class HostPort(Protocol):
    """The core's outward API surface (consumed by host adapters).

    Sketched in Phase 0; bodies land in Phases 1–2.
    """

    async def ingest(self, events: list[LearningEvent]) -> None: ...
    async def recall(
        self, learner_id: str, query: str, budget: int
    ) -> RecallResult: ...
    async def consolidate(self, learner_id: str) -> None: ...
    async def graph(
        self, learner_id: str, focus: str | None = None
    ) -> GraphView: ...
```

- [ ] **Step 4: Implement `tests/fakes.py`**

```python
"""In-process fakes implementing the core Protocols. Used by all non-live tests."""

from __future__ import annotations

from typing import Any

from engram.core.models import Completion, LearningEvent, Message, Node


class FakeLLM:
    def __init__(
        self,
        canned_text: str = "ok",
        canned_embedding: list[float] | None = None,
    ) -> None:
        self.canned_text = canned_text
        self.canned_embedding = canned_embedding or [0.0] * 1024
        self.complete_calls: list[tuple[str, list[Message], dict | None]] = []
        self.embed_calls: list[list[str]] = []

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        self.complete_calls.append((role, messages, schema))
        return Completion(text=self.canned_text, usage={"role": role}, model=f"fake-{role}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        return [list(self.canned_embedding) for _ in texts]


class FakeStorage:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    async def health(self) -> bool:
        return self.healthy

    async def insert_event(self, e: LearningEvent) -> str:
        raise NotImplementedError("Phase 1")

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        raise NotImplementedError("Phase 1")
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_ports_contract.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Stop and ask the user to commit**

```bash
git add src/engram/core/ports.py tests/fakes.py tests/test_ports_contract.py
git status
```

Suggested message:

```
feat(core): LLMPort, StoragePort, HostPort Protocols and in-process fakes
```

---

## Task 5: Migration SQL + docker-compose (db service)

**Files:**
- Create: `migrations/0001_engram_schema.sql`
- Create: `docker-compose.yml`

- [ ] **Step 1: Write `migrations/0001_engram_schema.sql`**

```sql
-- Phase 0 schema. Full DDL from the spec; no logic uses tables other than the
-- existence check in StoragePort.health() yet.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS engram_nodes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id    text NOT NULL,
  type          text NOT NULL CHECK (type IN ('concept','preference','goal')),
  label         text NOT NULL,
  summary       text,
  mastery       real,
  confidence    real,
  salience      real,
  embedding     vector(1024),
  source_refs   jsonb NOT NULL DEFAULT '[]'::jsonb,
  forgotten_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_nodes_embedding_hnsw
  ON engram_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS engram_nodes_learner_type
  ON engram_nodes (learner_id, type);

CREATE TABLE IF NOT EXISTS engram_edges (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  source_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  target_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  type        text NOT NULL CHECK (type IN ('prerequisite','relates_to','part_of')),
  weight      real NOT NULL DEFAULT 1.0,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_edges_learner_source
  ON engram_edges (learner_id, source_id);

CREATE TABLE IF NOT EXISTS engram_evidence (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  content     text,
  source_ref  jsonb,
  embedding   vector(1024),
  importance  real,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_evidence_node ON engram_evidence (node_id);

CREATE TABLE IF NOT EXISTS engram_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id      text NOT NULL,
  type            text NOT NULL,
  text            text,
  refs            jsonb NOT NULL DEFAULT '{}'::jsonb,
  signals         jsonb NOT NULL DEFAULT '{}'::jsonb,
  ts              timestamptz NOT NULL DEFAULT now(),
  consolidated_at timestamptz
);
CREATE INDEX IF NOT EXISTS engram_events_pending
  ON engram_events (learner_id) WHERE consolidated_at IS NULL;

CREATE TABLE IF NOT EXISTS engram_audit (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  op          text NOT NULL,
  input_refs  jsonb,
  output_refs jsonb,
  rationale   text,
  model       text,
  tokens      int,
  cost        numeric,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_audit_learner_ts ON engram_audit (learner_id, ts);

CREATE TABLE IF NOT EXISTS engram_mastery_history (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  mastery     real,
  confidence  real,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_mastery_history_node_ts
  ON engram_mastery_history (node_id, ts);
```

- [ ] **Step 2: Write `docker-compose.yml` (db only — app added in Task 14)**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: engram
      POSTGRES_PASSWORD: engram
      POSTGRES_DB: engram
    ports:
      - "5432:5432"
    volumes:
      - ./migrations:/docker-entrypoint-initdb.d:ro
      - engram_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engram -d engram"]
      interval: 2s
      timeout: 2s
      retries: 30

volumes:
  engram_pgdata:
```

The `docker-entrypoint-initdb.d` mount runs `0001_engram_schema.sql` on first DB
init. `pgvector/pgvector:pg16` already ships the `vector` extension.

- [ ] **Step 3: Bring the db up and verify the migration applied**

```bash
docker compose up -d db
# wait for healthy
until [ "$(docker inspect -f '{{.State.Health.Status}}' $(docker compose ps -q db))" = "healthy" ]; do sleep 1; done
docker compose exec -T db psql -U engram -d engram -c "\dt engram_*"
```

Expected: lists `engram_audit`, `engram_edges`, `engram_evidence`, `engram_events`, `engram_mastery_history`, `engram_nodes`.

- [ ] **Step 4: Verify pgvector and a round-trip**

```bash
docker compose exec -T db psql -U engram -d engram -c "SELECT extname FROM pg_extension WHERE extname='vector';"
docker compose exec -T db psql -U engram -d engram -c "SELECT array_fill(0.1::real, ARRAY[1024])::vector(1024) <-> array_fill(0.1::real, ARRAY[1024])::vector(1024);"
```

Expected: `vector` extension listed; the distance query returns `0` (or `0.0`).

- [ ] **Step 5: Stop and ask the user to commit**

```bash
git add migrations/0001_engram_schema.sql docker-compose.yml
git status
```

Suggested message:

```
feat(db): initial schema (nodes/edges/evidence/events/audit/mastery_history) + pgvector compose
```

---

## Task 6: PostgresStorage adapter — `health()` only (TDD against live db)

**Files:**
- Create: `src/engram/adapters/storage/postgres.py`
- Test: `tests/test_storage_postgres.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
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
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_storage_postgres.py`:

```python
"""Live tests against the docker-compose pgvector container.

Bring it up first: `docker compose up -d db`.
"""

import pytest

from engram.adapters.storage.postgres import PostgresStorage


@pytest.mark.asyncio
async def test_health_true_against_live_db(database_url: str) -> None:
    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        assert await storage.health() is True
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_health_false_when_db_unreachable() -> None:
    # Unused port; connection must fail fast and health() must return False.
    storage = PostgresStorage("postgresql://engram:engram@127.0.0.1:1/engram")
    # connect() may itself raise — that's fine; health() is the contract.
    try:
        await storage.connect()
    except Exception:
        pass
    assert await storage.health() is False


@pytest.mark.asyncio
async def test_phase_n_methods_raise_not_implemented(database_url: str) -> None:
    from engram.core.models import LearningEvent

    storage = PostgresStorage(database_url)
    await storage.connect()
    try:
        with pytest.raises(NotImplementedError, match="Phase 1"):
            await storage.insert_event(LearningEvent(learner_id="x", type="utterance"))
        with pytest.raises(NotImplementedError, match="Phase 1"):
            await storage.vector_search("x", [0.0] * 1024, 5)
    finally:
        await storage.close()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
docker compose up -d db
pytest tests/test_storage_postgres.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.adapters.storage.postgres'`.

- [ ] **Step 4: Implement `src/engram/adapters/storage/postgres.py`**

```python
"""asyncpg-backed StoragePort. Phase 0: only `health()` has a real body."""

from __future__ import annotations

import asyncpg

from engram.core.models import LearningEvent, Node


class PostgresStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        # Small pool — we're hello-world. Phase 1+ will tune.
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                # Cheap reachability probe + assert the schema is present.
                val = await conn.fetchval("SELECT 1")
                if val != 1:
                    return False
                exists = await conn.fetchval(
                    "SELECT to_regclass('public.engram_nodes') IS NOT NULL"
                )
                return bool(exists)
        except Exception:
            return False

    async def insert_event(self, e: LearningEvent) -> str:
        raise NotImplementedError("Phase 1")

    async def vector_search(
        self, learner_id: str, query_vec: list[float], k: int
    ) -> list[Node]:
        raise NotImplementedError("Phase 1")
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_storage_postgres.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Stop and ask the user to commit**

```bash
git add src/engram/adapters/storage/postgres.py tests/test_storage_postgres.py tests/conftest.py
git status
```

Suggested message:

```
feat(storage): asyncpg PostgresStorage with health() + Phase-N stubs
```

---

## Task 7: Settings / role→model config (TDD)

**Files:**
- Create: `src/engram/app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import pytest

from engram.app.config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example/v1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "tutor-x")
    monkeypatch.setenv("ENGRAM_MODEL_EXTRACTOR", "extractor-x")
    monkeypatch.setenv("ENGRAM_MODEL_REFLECTOR", "reflector-x")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "embedder-x")
    monkeypatch.setenv("ENGRAM_EMBEDDING_DIM", "1024")

    s = Settings()
    assert s.dashscope_api_key == "sk-test"
    assert s.dashscope_base_url == "https://example/v1"
    assert s.database_url == "postgresql://x"
    assert s.embedding_dim == 1024
    assert s.model_for("tutor") == "tutor-x"
    assert s.model_for("extractor") == "extractor-x"
    assert s.model_for("reflector") == "reflector-x"
    assert s.model_for("embedder") == "embedder-x"


def test_model_for_unknown_role(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "x")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "x")
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("ENGRAM_MODEL_TUTOR", "t")
    monkeypatch.setenv("ENGRAM_MODEL_EXTRACTOR", "e")
    monkeypatch.setenv("ENGRAM_MODEL_REFLECTOR", "r")
    monkeypatch.setenv("ENGRAM_MODEL_EMBEDDER", "em")
    s = Settings()
    with pytest.raises(KeyError):
        s.model_for("nonsense")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.app.config'`.

- [ ] **Step 3: Implement `src/engram/app/config.py`**

```python
"""env-loaded settings. The role->model map is the #1 cost lever (spec §2)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Required
    dashscope_api_key: str
    dashscope_base_url: str
    database_url: str

    # Role -> model
    model_tutor: str = Field(alias="ENGRAM_MODEL_TUTOR")
    model_extractor: str = Field(alias="ENGRAM_MODEL_EXTRACTOR")
    model_reflector: str = Field(alias="ENGRAM_MODEL_REFLECTOR")
    model_embedder: str = Field(alias="ENGRAM_MODEL_EMBEDDER")

    embedding_dim: int = Field(default=1024, alias="ENGRAM_EMBEDDING_DIM")

    def model_for(self, role: str) -> str:
        try:
            return {
                "tutor": self.model_tutor,
                "extractor": self.model_extractor,
                "reflector": self.model_reflector,
                "embedder": self.model_embedder,
            }[role]
        except KeyError as e:
            raise KeyError(f"Unknown LLM role: {role!r}") from e
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Stop and ask the user to commit**

```bash
git add src/engram/app/config.py tests/test_config.py
git status
```

Suggested message:

```
feat(config): Settings with role->model tiering map
```

---

## Task 8: DashScope `LLMPort` adapter (TDD with mocked client + skipif live test)

**Files:**
- Create: `src/engram/adapters/llm/dashscope.py`
- Test: `tests/test_dashscope_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashscope_adapter.py`:

```python
"""Unit tests use a fake OpenAI client (the SDK's surface is small). The live
test runs only when `DASHSCOPE_API_KEY` is in the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from engram.adapters.llm.dashscope import DashScopeLLM
from engram.core.models import Message


# ---------- fake OpenAI client ----------


@dataclass
class _FakeChoiceMsg:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeChoiceMsg


@dataclass
class _FakeUsage:
    prompt_tokens: int = 1
    completion_tokens: int = 2
    total_tokens: int = 3


@dataclass
class _FakeChatCompletion:
    choices: list[_FakeChoice]
    usage: _FakeUsage
    model: str


@dataclass
class _FakeEmbedItem:
    embedding: list[float]


@dataclass
class _FakeEmbedResp:
    data: list[_FakeEmbedItem]
    model: str
    usage: _FakeUsage


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeChatCompletion(
            choices=[_FakeChoice(message=_FakeChoiceMsg(content="hello from fake"))],
            usage=_FakeUsage(),
            model=kwargs["model"],
        )


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        n = len(kwargs["input"])
        return _FakeEmbedResp(
            data=[_FakeEmbedItem(embedding=[0.1] * 4) for _ in range(n)],
            model=kwargs["model"],
            usage=_FakeUsage(),
        )


class _FakeOpenAI:
    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.embeddings = _FakeEmbeddings()


# ---------- tests ----------


@pytest.mark.asyncio
async def test_complete_uses_role_to_model_map():
    role_to_model = {"tutor": "tutor-x", "extractor": "ext-x", "embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    result = await llm.complete("tutor", [Message(role="user", content="hi")])

    assert result.text == "hello from fake"
    assert result.model == "tutor-x"
    assert result.usage["total_tokens"] == 3
    sent = fake.chat.completions.calls[0]
    assert sent["model"] == "tutor-x"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "response_format" not in sent


@pytest.mark.asyncio
async def test_complete_passes_schema_as_json_response_format():
    role_to_model = {"extractor": "ext-x", "embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    await llm.complete("extractor", [Message(role="user", content="...")], schema=schema)

    sent = fake.chat.completions.calls[0]
    assert sent["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_embed_uses_embedder_model_and_batches():
    role_to_model = {"embedder": "emb-x"}
    fake = _FakeOpenAI()
    llm = DashScopeLLM(client=fake, role_to_model=role_to_model)

    vectors = await llm.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert vectors[0] == [0.1, 0.1, 0.1, 0.1]
    sent = fake.embeddings.calls[0]
    assert sent["model"] == "emb-x"
    assert sent["input"] == ["a", "b", "c"]


@pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY not set — live DashScope test skipped",
)
@pytest.mark.asyncio
async def test_live_dashscope_completion_and_embedding():
    """The proof beat for Phase 0a-local: when a real key is present, this hits
    DashScope's OpenAI-compatible endpoint and verifies both endpoints."""
    from engram.adapters.llm.dashscope import build_dashscope_llm
    from engram.app.config import Settings

    settings = Settings()  # reads .env
    llm = build_dashscope_llm(settings)

    r = await llm.complete("tutor", [Message(role="user", content="Say 'pong'.")])
    assert r.text and "pong" in r.text.lower()

    vectors = await llm.embed(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == settings.embedding_dim
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_dashscope_adapter.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.adapters.llm.dashscope'`.

- [ ] **Step 3: Implement `src/engram/adapters/llm/dashscope.py`**

```python
"""DashScope LLMPort adapter — the file the submission's "uses Alibaba APIs"
link points at. Wraps the OpenAI SDK aimed at DashScope's OpenAI-compatible
endpoint (https://dashscope-intl.aliyuncs.com/compatible-mode/v1).

All Alibaba Cloud / Qwen calls in Engram flow through here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from engram.core.models import Completion, Message


class _AsyncOpenAILike(Protocol):
    chat: Any
    embeddings: Any


class DashScopeLLM:
    """Implements core.ports.LLMPort against DashScope's OpenAI-compatible API."""

    def __init__(
        self,
        client: _AsyncOpenAILike,
        role_to_model: dict[str, str],
    ) -> None:
        self._client = client
        self._role_to_model = role_to_model

    async def complete(
        self,
        role: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> Completion:
        model = self._resolve(role)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [asdict(m) for m in messages],
        }
        if schema is not None:
            # DashScope's OpenAI-compatible endpoint accepts json_object;
            # the prompt itself must describe the schema for the model.
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content if resp.choices else None
        usage = self._usage_dict(getattr(resp, "usage", None))
        return Completion(text=text, usage=usage, model=getattr(resp, "model", model))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._resolve("embedder")
        resp = await self._client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in resp.data]

    def _resolve(self, role: str) -> str:
        try:
            return self._role_to_model[role]
        except KeyError as e:
            raise KeyError(f"No model configured for role {role!r}") from e

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        # Works for both the SDK's pydantic model and our test fake.
        for attr in ("model_dump", "dict"):
            fn = getattr(usage, attr, None)
            if callable(fn):
                return fn()
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }


def build_dashscope_llm(settings: Any) -> DashScopeLLM:
    """Composition helper: build a DashScopeLLM from a Settings instance."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )
    role_to_model = {
        "tutor": settings.model_for("tutor"),
        "extractor": settings.model_for("extractor"),
        "reflector": settings.model_for("reflector"),
        "embedder": settings.model_for("embedder"),
    }
    return DashScopeLLM(client=client, role_to_model=role_to_model)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_dashscope_adapter.py -v
```

Expected: 3 passed, 1 skipped (`DASHSCOPE_API_KEY not set ...`).

- [ ] **Step 5: Stop and ask the user to commit**

```bash
git add src/engram/adapters/llm/dashscope.py tests/test_dashscope_adapter.py
git status
```

Suggested message:

```
feat(llm): DashScope LLMPort adapter (Alibaba Model Studio proof file)
```

---

## Task 9: Composition root (`deps.py`)

**Files:**
- Create: `src/engram/app/deps.py`

This task has no new test — it's wiring used by Task 10's app tests. The next task fails until this exists.

- [ ] **Step 1: Implement `src/engram/app/deps.py`**

```python
"""Composition root: build adapters from Settings and expose FastAPI dependency
providers. The app module is the ONLY place that wires concrete adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from engram.adapters.llm.dashscope import DashScopeLLM, build_dashscope_llm
from engram.adapters.storage.postgres import PostgresStorage
from engram.app.config import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Singletons for the process lifetime. main.py manages connect/close on
# startup/shutdown. Tests override via FastAPI's dependency_overrides.
_storage: PostgresStorage | None = None
_llm: DashScopeLLM | None = None


async def init_singletons(settings: Settings | None = None) -> None:
    global _storage, _llm
    settings = settings or get_settings()
    _storage = PostgresStorage(settings.database_url)
    await _storage.connect()
    _llm = build_dashscope_llm(settings)


async def shutdown_singletons() -> None:
    global _storage, _llm
    if _storage is not None:
        await _storage.close()
    _storage = None
    _llm = None


def get_storage() -> Any:
    if _storage is None:
        raise RuntimeError("Storage not initialized; call init_singletons() first")
    return _storage


def get_llm() -> Any:
    if _llm is None:
        raise RuntimeError("LLM not initialized; call init_singletons() first")
    return _llm
```

- [ ] **Step 2: Smoke check the import**

```bash
python -c "from engram.app.deps import get_settings, get_storage, get_llm; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Stop and ask the user to commit**

```bash
git add src/engram/app/deps.py
git status
```

Suggested message:

```
feat(app): composition root with init/shutdown lifecycle
```

---

## Task 10: FastAPI app — `/health` and `/llm-ping` (TDD)

**Files:**
- Create: `src/engram/app/main.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app.py`:

```python
"""End-to-end app tests using fakes for both ports — no DB, no network."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from engram.app import deps
from engram.app.main import app
from engram.core.models import Message
from tests.fakes import FakeLLM, FakeStorage


@pytest.fixture
def fakes(monkeypatch):
    fake_llm = FakeLLM(canned_text="pong", canned_embedding=[0.1] * 1024)
    fake_storage = FakeStorage(healthy=True)
    app.dependency_overrides[deps.get_llm] = lambda: fake_llm
    app.dependency_overrides[deps.get_storage] = lambda: fake_storage
    try:
        yield fake_llm, fake_storage
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_ok_when_storage_healthy(fakes):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


@pytest.mark.asyncio
async def test_health_degraded_when_storage_unhealthy(fakes):
    fake_llm, fake_storage = fakes
    fake_storage.healthy = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 503
    assert r.json()["db"] == "down"


@pytest.mark.asyncio
async def test_llm_ping_returns_completion_and_embedding(fakes):
    fake_llm, _ = fakes
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/llm-ping", json={"prompt": "ping"})
    assert r.status_code == 200
    body = r.json()
    assert body["completion"] == "pong"
    assert body["embedding_dim"] == 1024
    assert body["usage"] == {"role": "tutor"}

    # And it actually exercised both methods on the LLM port:
    assert fake_llm.complete_calls and fake_llm.complete_calls[0][0] == "tutor"
    sent_msgs = fake_llm.complete_calls[0][1]
    assert sent_msgs == [Message(role="user", content="ping")]
    assert fake_llm.embed_calls == [["ping"]]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_app.py -v
```

Expected: `ModuleNotFoundError: No module named 'engram.app.main'`.

- [ ] **Step 3: Implement `src/engram/app/main.py`**

```python
"""Engram Phase 0 FastAPI app. Two endpoints:

- GET  /health   -> liveness + DB reachability (no LLM)
- POST /llm-ping -> exercises LLMPort.complete + .embed (the Phase 0 proof beat)

Composition lives in deps.py; this module wires endpoints only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from engram.app import deps
from engram.core.models import Message


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await deps.init_singletons()
    try:
        yield
    finally:
        await deps.shutdown_singletons()


app = FastAPI(title="Engram", version="0.0.1", lifespan=_lifespan)


@app.get("/health")
async def health(storage: Any = Depends(deps.get_storage)) -> dict[str, str]:
    ok = await storage.health()
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "degraded", "db": "down"})
    return {"status": "ok", "db": "ok"}


class _PingIn(BaseModel):
    prompt: str


class _PingOut(BaseModel):
    completion: str | None
    embedding_dim: int
    usage: dict[str, Any]
    model: str | None


@app.post("/llm-ping", response_model=_PingOut)
async def llm_ping(
    body: _PingIn,
    llm: Any = Depends(deps.get_llm),
) -> _PingOut:
    completion = await llm.complete("tutor", [Message(role="user", content=body.prompt)])
    vectors = await llm.embed([body.prompt])
    return _PingOut(
        completion=completion.text,
        embedding_dim=len(vectors[0]) if vectors else 0,
        usage=completion.usage,
        model=completion.model,
    )
```

Note: when FastAPI raises an `HTTPException` with a `dict` detail, the response
body is `{"detail": {...}}`. The test asserts `r.json()["db"] == "down"` —
update either the test or the response if you want strict equality. The
current test reads `r.json()["db"]`, so adjust the assertion to
`r.json()["detail"]["db"] == "down"` if needed when you run it.

- [ ] **Step 4: Adjust the failing-storage test if needed**

If Step 3 ran and `test_health_degraded_when_storage_unhealthy` fails on the
shape of the JSON, change the test's last line to:

```python
    assert r.json()["detail"]["db"] == "down"
```

Re-run.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_app.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the whole suite**

```bash
pytest -v
```

Expected: all green; the live DashScope test is skipped without a key. The
storage tests need `docker compose up -d db` to be running (Task 5).

- [ ] **Step 7: Stop and ask the user to commit**

```bash
git add src/engram/app/main.py tests/test_app.py
git status
```

Suggested message:

```
feat(app): /health and /llm-ping endpoints with dependency-injected ports
```

---

## Task 11: Dockerfile + app service in docker-compose

**Files:**
- Create: `docker/Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write `docker/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg / pgvector / general health
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -U pip && pip install -e .

EXPOSE 8000

# uvicorn workers=1 — keep it simple for Phase 0; ECS hosts the single instance.
CMD ["uvicorn", "engram.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Add the app service to `docker-compose.yml`**

Modify `docker-compose.yml` to:

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: engram
      POSTGRES_PASSWORD: engram
      POSTGRES_DB: engram
    ports:
      - "5432:5432"
    volumes:
      - ./migrations:/docker-entrypoint-initdb.d:ro
      - engram_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engram -d engram"]
      interval: 2s
      timeout: 2s
      retries: 30

  app:
    build:
      context: .
      dockerfile: docker/Dockerfile
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://engram:engram@db:5432/engram
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-replace-me}
      DASHSCOPE_BASE_URL: ${DASHSCOPE_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}
      ENGRAM_MODEL_TUTOR: ${ENGRAM_MODEL_TUTOR:-qwen3-vl-plus}
      ENGRAM_MODEL_EXTRACTOR: ${ENGRAM_MODEL_EXTRACTOR:-qwen3.5-flash}
      ENGRAM_MODEL_REFLECTOR: ${ENGRAM_MODEL_REFLECTOR:-qwen3-max}
      ENGRAM_MODEL_EMBEDDER: ${ENGRAM_MODEL_EMBEDDER:-text-embedding-v4}
      ENGRAM_EMBEDDING_DIM: ${ENGRAM_EMBEDDING_DIM:-1024}
    ports:
      - "8000:8000"

volumes:
  engram_pgdata:
```

- [ ] **Step 3: Build the image and run a health check**

```bash
docker compose build app
docker compose up -d
# wait for the app to come up
until curl -fsS http://localhost:8000/health >/dev/null 2>&1; do sleep 1; done
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok","db":"ok"}`

- [ ] **Step 4: Try the LLM ping (will 401 / error from DashScope without a real key — that's expected proof the request is being made)**

```bash
curl -s -X POST http://localhost:8000/llm-ping \
  -H 'content-type: application/json' \
  -d '{"prompt":"Say pong"}' | head -c 500
```

Expected: either a 200 with a real Qwen completion (if the user has placed a
valid key in `.env` and `docker compose` picked it up), or a 5xx with a
DashScope auth error. Either way proves the path is wired. The user can later
re-run with a real key.

- [ ] **Step 5: Tear down**

```bash
docker compose down
```

- [ ] **Step 6: Stop and ask the user to commit**

```bash
git add docker/Dockerfile docker-compose.yml
git status
```

Suggested message:

```
feat(docker): app Dockerfile and compose service wiring app to db
```

---

## Task 12: README + 0b deploy runbook

**Files:**
- Modify: `README.md`
- Create: `docs/deploy.md`

- [ ] **Step 1: Replace `README.md`**

```markdown
# Engram

App-agnostic memory core for AI tutors. Two agents over one graph: a slow
**Memory Keeper** consolidates raw learning events into a typed knowledge graph;
a fast **Recall** returns a token-budgeted subgraph on the hot path. Submission
to the Qwen Cloud Global AI Hackathon (Track 1: MemoryAgent).

- Full architecture: [`DESIGN.md`](./DESIGN.md)
- Phase 0 spec: [`docs/superpowers/specs/2026-05-27-engram-phase-0-foundations-design.md`](./docs/superpowers/specs/2026-05-27-engram-phase-0-foundations-design.md)
- Phase 0 plan: [`docs/superpowers/plans/2026-05-28-engram-phase-0-foundations.md`](./docs/superpowers/plans/2026-05-28-engram-phase-0-foundations.md)

## Phase 0 status

Foundations only — the agnostic core (ports + domain types), the pgvector
schema, a DashScope `LLMPort` adapter, and a hello-world FastAPI app. No memory
logic, no voice, no viz yet. Those are Phases 1–5 in `DESIGN.md`.

The DashScope adapter — [`src/engram/adapters/llm/dashscope.py`](./src/engram/adapters/llm/dashscope.py) —
is the Alibaba Cloud APIs proof file.

## Run locally

```bash
cp .env.example .env
# edit .env and paste your DashScope key into DASHSCOPE_API_KEY
docker compose up --build
curl http://localhost:8000/health
curl -X POST http://localhost:8000/llm-ping \
     -H 'content-type: application/json' \
     -d '{"prompt":"Say pong."}'
```

## Run tests

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db        # the storage tests need the pgvector container
pytest -v
```

The DashScope live test (`test_live_dashscope_completion_and_embedding`)
auto-skips unless `DASHSCOPE_API_KEY` is set.

## Project layout

```
src/engram/
  core/        # pure: Protocols (HostPort/StoragePort/LLMPort) + dataclasses
  adapters/
    storage/postgres.py   # asyncpg + pgvector (works on RDS, local, Supabase)
    llm/dashscope.py      # OpenAI SDK -> DashScope OpenAI-compatible endpoint
  app/         # FastAPI + composition root
migrations/    # 0001_engram_schema.sql
tests/         # contracts + fakes + live tests
```

## Deploy

See [`docs/deploy.md`](./docs/deploy.md) for the Phase 0b runbook (Alibaba
account setup → RDS → ECS → live `/llm-ping` recording).

## License

MIT — see [`LICENSE`](./LICENSE).
```

- [ ] **Step 2: Write `docs/deploy.md` (Phase 0b runbook)**

```markdown
# Engram — Phase 0b deploy runbook (Alibaba Cloud)

This runbook turns the local Phase 0a build into the hackathon's required
proof: the backend running on Alibaba Cloud and calling DashScope. Execute it
**once you have an Alibaba account + Model Studio (DashScope) API key**.

## Prerequisites

- Alibaba Cloud account (sign up at https://www.alibabacloud.com/).
- Alibaba CLI optional but recommended.
- Local repo on the `main` branch, all Phase 0a tests passing.

## 1. Get a DashScope API key

1. Open Model Studio (Alibaba Cloud console → Model Studio / DashScope).
2. Create an API key. Treat it like any other secret — never commit it.
3. Paste it into your local `.env` (`DASHSCOPE_API_KEY=...`) and re-run
   `pytest tests/test_dashscope_adapter.py -v -k live` locally to confirm the
   live test passes.

## 2. Provision RDS for PostgreSQL with pgvector

1. Console → ApsaraDB RDS → create a PostgreSQL **16** instance (small
   spec is fine for the demo).
2. Create an account `engram` and a database `engram`.
3. Add your client IP (and later the ECS instance's IP) to the RDS allowlist.
4. Connect with `psql` (or the console SQL workbench):
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   CREATE EXTENSION IF NOT EXISTS pgcrypto;
   ```
5. Apply the migration:
   ```bash
   psql "$RDS_DSN" -f migrations/0001_engram_schema.sql
   ```
   Verify: `psql "$RDS_DSN" -c "\dt engram_*"` lists all six tables.

## 3. Build the image and push to ACR (Alibaba Container Registry)

```bash
docker build -t engram:0.0.1 -f docker/Dockerfile .
# Tag for ACR (region/namespace/repo from your ACR setup)
docker tag engram:0.0.1 registry.<region>.aliyuncs.com/<ns>/engram:0.0.1
docker login --username=<acr-user> registry.<region>.aliyuncs.com
docker push registry.<region>.aliyuncs.com/<ns>/engram:0.0.1
```

## 4. Run on ECS

1. Console → ECS → create a small instance (Ubuntu/Anolis, 2vCPU/4GB is fine).
2. Open port 8000 in the security group (and 22 for SSH).
3. SSH in, install Docker, `docker login` to ACR, pull the image.
4. Run with env wired to RDS + DashScope (do NOT bake the key into the image):
   ```bash
   docker run -d --name engram --restart=always -p 8000:8000 \
     -e DATABASE_URL="postgresql://engram:<pw>@<rds-host>:5432/engram" \
     -e DASHSCOPE_API_KEY="<your key>" \
     -e DASHSCOPE_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1" \
     -e ENGRAM_MODEL_TUTOR="qwen3-vl-plus" \
     -e ENGRAM_MODEL_EXTRACTOR="qwen3.5-flash" \
     -e ENGRAM_MODEL_REFLECTOR="qwen3-max" \
     -e ENGRAM_MODEL_EMBEDDER="text-embedding-v4" \
     -e ENGRAM_EMBEDDING_DIM=1024 \
     registry.<region>.aliyuncs.com/<ns>/engram:0.0.1
   ```

## 5. Proof of life (screen-record this)

```bash
curl -s http://<ecs-public-ip>:8000/health
curl -s -X POST http://<ecs-public-ip>:8000/llm-ping \
  -H 'content-type: application/json' \
  -d '{"prompt":"Say pong."}'
```

Both calls returning OK from the ECS public IP — combined with the Model Studio
console showing the request — is the hackathon's "backend on Alibaba calling
Alibaba services" proof. Keep the recording short and the URLs visible.

## 6. Submission link

Point the submission's "uses Alibaba Cloud APIs" link at the GitHub permalink
for [`src/engram/adapters/llm/dashscope.py`](../src/engram/adapters/llm/dashscope.py).
```

- [ ] **Step 3: Sanity-render the README and runbook**

```bash
head -40 README.md
head -40 docs/deploy.md
```

Expected: clean markdown, no obvious truncation.

- [ ] **Step 4: Stop and ask the user to commit**

```bash
git add README.md docs/deploy.md
git status
```

Suggested message:

```
docs: README + Phase 0b Alibaba deploy runbook
```

---

## Task 13: End-to-end smoke + final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test pass (no DashScope key)**

```bash
source .venv/bin/activate
docker compose up -d db
pytest -v
docker compose down
```

Expected: every test passes; only `test_live_dashscope_completion_and_embedding`
is skipped (with the no-key reason).

- [ ] **Step 2: Compose-up smoke**

```bash
docker compose up --build -d
until curl -fsS http://localhost:8000/health >/dev/null 2>&1; do sleep 1; done
echo "--- /health ---"
curl -s http://localhost:8000/health
echo
echo "--- /llm-ping (no/bad key expected to error from DashScope; that's fine) ---"
curl -s -X POST http://localhost:8000/llm-ping \
     -H 'content-type: application/json' -d '{"prompt":"Say pong."}' | head -c 800
docker compose down
```

Expected: `/health` returns `{"status":"ok","db":"ok"}`. `/llm-ping` either
returns a real Qwen completion (key in `.env` is real) or surfaces a DashScope
auth/permission error — either way confirming the wiring is live.

- [ ] **Step 3: Capture the Phase 0a "Definition of Done" checklist**

Check each spec §10 (0a) line by hand:
- [ ] `docker compose up` brings db + app and migration applied
- [ ] `pytest -v` is green (DashScope live skipped)
- [ ] `GET /health` returns `{"status":"ok","db":"ok"}`
- [ ] `POST /llm-ping` succeeds the moment a valid `DASHSCOPE_API_KEY` is in `.env`
- [ ] `LICENSE` (MIT) at root
- [ ] `README.md` documents run + points at the 0b runbook

If any item is no, file a corrective task and rerun.

- [ ] **Step 4: Stop and ask the user to commit the plan tracking file**

If the executor used a generated execution log, stage it; otherwise this is a
no-op. Suggested message:

```
chore: phase 0a foundations complete
```

---

## Self-review notes (executor: skip — for the plan author only)

**Spec coverage check (vs. `docs/superpowers/specs/2026-05-27-engram-phase-0-foundations-design.md`):**

- §2 Locked decisions — Python/FastAPI ✔ T2, ECS (Dockerfile only in 0a; deploy in 0b runbook) ✔ T11/T12, RDS/pgvector ✔ T5/T12, MIT ✔ T1, Protocols+DI ✔ T4/T9, DashScope OpenAI-compat ✔ T8.
- §3a buildable — repo+LICENSE ✔ T1, pyproject ✔ T2, core ✔ T3/T4, migration ✔ T5, storage ✔ T6, config ✔ T7, DashScope adapter ✔ T8, FastAPI app ✔ T10, Dockerfile/compose ✔ T11, tests throughout.
- §3b access-gated — runbook ✔ T12.
- §4 Ports — LLMPort ✔ T4, StoragePort ✔ T4 (signatures) + T6 (impl), HostPort ✔ T4 (declared).
- §5 Domain models — ✔ T3.
- §6 Schema — ✔ T5 (full DDL incl. `forgotten_at`, HNSW, learner_id scoping; RLS deferred per spec note).
- §7 DashScope adapter — ✔ T8 (chat + embeddings + role→model + factory).
- §8 FastAPI — ✔ T10 (/health + /llm-ping with role="tutor" and embed).
- §9 Testing — port contracts ✔ T4, schema ✔ T5 step 4 + T6, DashScope skipif live ✔ T8, no mocking of own code ✔.
- §10 DoD — checked end-to-end in T13.
- §11 Out of scope — Keeper/Recall/voice/viz/cron/RLS/auth are absent from the plan ✔.

**Placeholder scan:** none found (no TBD/TODO, no "implement later", every code step has full code, every command has expected output).

**Type consistency:** `Settings.model_for(role)` used identically in T7 and T8; `DashScopeLLM(client, role_to_model)` constructor matches T8 and T9; `PostgresStorage(dsn)` matches T6 and T9; `Message(role=, content=)` consistent across T3/T4/T8/T10; embedding dim `1024` consistent across `.env.example`, schema (`vector(1024)`), `Settings.embedding_dim`, and the FakeLLM default.
