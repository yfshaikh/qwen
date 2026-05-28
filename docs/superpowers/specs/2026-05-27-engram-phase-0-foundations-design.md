# Engram — Phase 0: Foundations (design spec)

> **Status:** Approved design, pre-implementation.
> **Date:** 2026-05-27.
> **Parent doc:** [`DESIGN.md`](../../../DESIGN.md) — the full Engram architecture and
> 6-phase plan. This spec covers **Phase 0 only** (the foundations / Alibaba
> de-risk slice). Later phases get their own spec → plan → build cycle.

---

## 1. Why Phase 0 exists

Engram's single disqualifying risk is the hackathon's gating requirement: the
backend must **run on Alibaba Cloud and call an Alibaba service**. Phase 0 exists
to prove that path end-to-end with a hello-world before any real feature is
built — plus to lay the agnostic-core skeleton everything else hangs off of.

Phase 0 deliverables (from `DESIGN.md` §8): new repo + LICENSE; core skeleton
with the 3 ports; pgvector schema; DashScope `LLMPort` adapter; hello-world
FastAPI deployed on Alibaba compute calling DashScope.

**Phase 0 is explicitly NOT:** the Memory Keeper, Recall, the voice host
adapter, the graph viz, or the eval harness. Those are Phases 1–5. The schema is
created in full now (cheap, and avoids migration churn), but no agent logic runs
against it yet.

## 2. Locked decisions

| Decision | Choice | Reason |
|---|---|---|
| Language / framework | Python 3.12 + FastAPI | Matches Starnotes; reuses its Dockerfile + voice WS later |
| Compute target | **Alibaba ECS** (container host) | Always-on → no cold-start risk in the live voice demo; full WebSocket support |
| Database | **ApsaraDB RDS for PostgreSQL 16 + pgvector** | Standard Postgres + pgvector (HNSW/IVFFlat); simpler/cheaper than PolarDB |
| DB access | All behind `StoragePort` | "Alibaba now, Supabase later" = one new adapter file, core untouched |
| Inference | DashScope OpenAI-compatible endpoint | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`; the OpenAI SDK pointed there |
| LICENSE | **MIT** at repo root | Simplest, maximally detectable, fine for Starnotes/Marfini reuse |
| Boundary mechanism | Python `Protocol`s + constructor injection | Pythonic, fake-able in tests, no DI framework |
| Serverless story | Deferred to Function Compute cron (Phase 5) | Live socket stays on always-on ECS; serverless lives in the Keeper sweep |

**Confirm-at-build-time (when the key exists), kept in config, never hard-coded:**
exact Qwen model slugs and prices. Current candidates: `qwen3-vl-plus` (tutor /
vision), a flash tier e.g. `qwen3.5-flash` (extractor), `qwen3-max` (reflector),
`text-embedding-v4` (embedder, flexible dims — Phase 0 fixes the column at
`vector(1024)`; changing the embedder's dimension is a migration).

## 3. Scope split: buildable-now vs. access-gated

Because there is no Alibaba account or DashScope key yet, Phase 0 is sequenced so
the access-gated parts never block the buildable parts.

### 3a — Local-buildable (no account / key needed)
- Repo scaffolding: `LICENSE` (MIT), `README.md`, `pyproject.toml`, `.env.example`,
  `docker/Dockerfile`, `docker-compose.yml` (app + local pgvector).
- `core/` skeleton: `ports.py` (3 Protocols), `models.py` (domain dataclasses).
- `migrations/0001_engram_schema.sql`: the full schema.
- `adapters/storage/postgres.py`: `StoragePort` impl (asyncpg + pgvector) — only
  the methods Phase 0 exercises need real bodies; the rest may `raise
  NotImplementedError` with a `# Phase N` marker.
- `adapters/llm/dashscope.py`: `LLMPort` impl (OpenAI SDK → DashScope base URL).
  ★ This is the file the submission's "uses Alibaba APIs" link points at.
- `app/main.py`: FastAPI with `GET /health` and `POST /llm-ping`.
- `app/config.py`: role→(provider, model, params) tiering map, loaded from env.
- Tests: port contract tests against fakes; a DashScope adapter test that
  **auto-skips** when `DASHSCOPE_API_KEY` is unset.

**Local DB note:** local dev uses a Docker `pgvector/pgvector:pg16` container.
Same dialect as RDS, so `0001_engram_schema.sql` is portable unchanged.

### 3b — Access-gated (needs your Alibaba account + DashScope key)
Delivered as a **runbook + verification checklist** (in `README.md` or
`docs/deploy.md`), executed together in a later session:
1. Sign up for Alibaba Cloud; enable Model Studio (DashScope) → get an API key.
2. Provision RDS for PostgreSQL 16; enable the `vector` extension; apply
   `0001_engram_schema.sql`.
3. Build + push the image; run it on an ECS instance; set env (incl. the key and
   RDS DSN) via the instance, not committed.
4. **Proof beat:** `POST /llm-ping` on the ECS box returns a real Qwen completion
   sourced from RDS connectivity — screen-recorded for the submission.

**Secrets handling (per user global rules):** only `.env.example` with
placeholders is ever created/committed. The real `.env` is created by the user;
Claude never reads it. Missing-env failures are surfaced, not investigated.

## 4. The ports (interface sketches)

`core/ports.py` — Protocols only; no implementation, no third-party imports.

```python
class LLMPort(Protocol):
    async def complete(self, role: str, messages: list[Message],
                       schema: dict | None = None) -> Completion: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class StoragePort(Protocol):
    # Phase 0 exercises a thin slice; full CRUD lands across Phases 1–2.
    async def health(self) -> bool: ...
    async def insert_event(self, e: LearningEvent) -> str: ...          # Phase 1
    async def vector_search(self, learner_id, query_vec, k) -> list[Node]: ...  # Phase 1
    # ... nodes/edges/evidence/audit/mastery_history CRUD: marked # Phase N

class HostPort(Protocol):
    # The core's outward API surface (consumed by host adapters). Sketched now,
    # bodies land in Phases 1–2. Listed for completeness; not implemented in 0.
    async def ingest(self, events: list[LearningEvent]) -> None: ...
    async def recall(self, learner_id, query, budget) -> RecallResult: ...
    async def consolidate(self, learner_id) -> None: ...
    async def graph(self, learner_id, focus=None) -> GraphView: ...
```

`Completion` carries `text | json` + `usage` (tokens/cost) so audit rows can be
written later. `role` maps through `config.py` to a concrete (provider, model).

## 5. Domain models

`core/models.py` — pure dataclasses, no persistence concerns:
`LearningEvent` (the agnostic input seam: `learner_id, type, text, refs,
signals, ts`), plus `Node`, `Edge`, `Evidence`, `Message`, `Completion`,
`RecallResult` (`text_block` + `subgraph`), `GraphView` (`nodes`, `edges`).
Enums/literals for node types (`concept|preference|goal`) and edge types
(`prerequisite|relates_to|part_of`) — the bounded type sets from `DESIGN.md`
§4.1. Defined now so adapters and tests share one vocabulary.

## 6. Schema — `migrations/0001_engram_schema.sql`

Full schema from `DESIGN.md` §4.1, made concrete. All tables learner-scoped.
`vector(1024)` matches the chosen embedder; an HNSW index on
`engram_nodes.embedding` for relevance search.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE engram_nodes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id    text NOT NULL,
  type          text NOT NULL CHECK (type IN ('concept','preference','goal')),
  label         text NOT NULL,
  summary       text,
  mastery       real,            -- 0..1 EWMA (BKT-swappable)
  confidence    real,            -- 0..1 memory self-audit
  salience      real,            -- decays; bumped on touch
  embedding     vector(1024),
  source_refs   jsonb DEFAULT '[]'::jsonb,
  forgotten_at  timestamptz,     -- soft-delete for visible forgetting (DESIGN §9.6)
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON engram_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON engram_nodes (learner_id, type);

CREATE TABLE engram_edges (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  source_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  target_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  type        text NOT NULL CHECK (type IN ('prerequisite','relates_to','part_of')),
  weight      real DEFAULT 1.0,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON engram_edges (learner_id, source_id);

CREATE TABLE engram_evidence (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  kind        text NOT NULL,   -- explained|asked_about|quiz_correct|quiz_wrong|note|struggle|demonstrated
  content     text,
  source_ref  jsonb,
  embedding   vector(1024),
  importance  real,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON engram_evidence (node_id);

CREATE TABLE engram_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id      text NOT NULL,
  type            text NOT NULL,
  text            text,
  refs            jsonb DEFAULT '{}'::jsonb,
  signals         jsonb DEFAULT '{}'::jsonb,
  ts              timestamptz NOT NULL DEFAULT now(),
  consolidated_at timestamptz   -- NULL = pending; the Keeper watermark
);
CREATE INDEX ON engram_events (learner_id) WHERE consolidated_at IS NULL;

CREATE TABLE engram_audit (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  op          text NOT NULL,   -- extract|link|merge|resolve_contradiction|decay|prune|recall
  input_refs  jsonb, output_refs jsonb,
  rationale   text,
  model       text, tokens int, cost numeric,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON engram_audit (learner_id, ts);

CREATE TABLE engram_mastery_history (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  mastery     real, confidence real,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON engram_mastery_history (node_id, ts);
```

**RLS deferred:** `DESIGN.md` says "RLS by owner," which presumes an auth model
(e.g. Supabase `auth.uid()`). RDS has no such identity in Phase 0, so RLS
policies are deferred to whenever an auth/host-identity model lands (Phase 1+).
`learner_id` columns exist now so scoping is enforceable at the query layer
immediately and via RLS later without a migration.

## 7. DashScope `LLMPort` adapter — `adapters/llm/dashscope.py`

The "uses Alibaba Cloud APIs" proof file. Wraps the OpenAI SDK pointed at the
DashScope OpenAI-compatible base URL:
- Constructor takes base URL + API key (from env) + the role→model config.
- `complete(role, messages, schema)`: resolves role→model via config, calls
  chat completions (`response_format`/JSON schema when `schema` given), returns
  `Completion{text|json, usage}`.
- `embed(texts)`: calls the embeddings endpoint with `text-embedding-v4`,
  returns vectors.
- A `FakeLLM` (in `tests/`, implementing `LLMPort`) returns canned output so the
  whole stack is testable with no key and no network.

## 8. FastAPI app — `app/main.py`

- `GET /health`: process up + `StoragePort.health()` (DB reachable). No LLM.
- `POST /llm-ping {prompt}`: calls `LLMPort.complete(role="tutor", ...)` and
  `LLMPort.embed([prompt])`; returns the completion text, the embedding length,
  and `usage`. This is the single endpoint that proves "FastAPI on Alibaba →
  DashScope" in 0b. Adapters are constructed in a small composition root (e.g.
  `app/deps.py`) and injected — the app module imports adapters; `core/` does not.

## 9. Testing strategy

- **Port contract tests** (`tests/test_ports_contract.py`): drive the app/core
  paths through `FakeLLM` + a fake or real-local `StoragePort`; assert shapes.
- **Schema test**: spin the pgvector container (compose), apply the migration,
  assert tables/extension/index exist and a `vector(1024)` round-trips.
- **DashScope adapter test** (`tests/test_dashscope_adapter.py`):
  `@pytest.mark.skipif(no DASHSCOPE_API_KEY)` — a real one-shot completion +
  embedding when a key is present; skipped in CI/local-without-key.
- No mocking of our own code; fakes implement the real Protocols.

## 10. Definition of done

**0a (now):**
- `docker compose up` → app + `pgvector/pgvector:pg16`; migration applied.
- `pytest` green (contracts + schema; DashScope test skipped without a key).
- `GET /health` → `{status: ok, db: ok}`.
- `POST /llm-ping` returns a real Qwen completion **the instant** a valid
  `DASHSCOPE_API_KEY` is in `.env` (verified locally by the user).
- `MIT LICENSE` at root; `README.md` documents run + the 0b runbook.

**0b (access-gated, later session):**
- `POST /llm-ping` returns a real Qwen completion from an **ECS** instance
  talking to **RDS for PostgreSQL** — screen-recorded for the submission.
- Submission "uses Alibaba APIs" link points at `adapters/llm/dashscope.py`.

## 11. Out of scope for Phase 0
Memory Keeper logic, Recall scoring/traversal, the voice host adapter, React
Flow viz, the eval harness, Function Compute cron, RLS policies, auth. The
schema and port signatures are created now so these land without churn.
