# Engram

**An app-agnostic memory core for AI tutors.** Engram turns a stream of generic
*learning events* into a **living knowledge graph of a learner**, maintained by a
background "Memory Keeper" agent and read on the hot path by a fast, LLM-free
"Recall". Built for the Qwen Cloud Global AI Hackathon, **Track 1 (MemoryAgent)**.

> **Status: working proof-of-concept.** Runs locally on Docker + OpenRouter. The
> memory pipeline (ingest → consolidate → recall → graph) runs with **no API key**
> (local embeddings); a key is only needed for the LLM-authored parts (Keeper
> extraction + tutor replies). The provider seam is one adapter, so moving to
> Alibaba Model Studio (DashScope) later is a config change — see [Transitioning](#transitioning-to-alibaba-cloud).

## The idea: two agents over one graph

- **Memory Keeper** (slow, offline, "asleep"): drains a learner's un-consolidated
  events and runs `extract → link → merge → resolve → decay → prune → snapshot`,
  distilling raw history into a typed graph of concepts/preferences/goals with
  scored evidence, EWMA mastery, and *timely forgetting*. All expensive reasoning
  lives here, amortized over a whole sitting (≈ one batched LLM call).
- **Recall** (fast, hot path, **no LLM reasoning**): a tutor turn asks "what
  matters about this learner + this topic right now" and gets a small,
  token-budgeted subgraph — one embedding + a vector query + a bounded traversal.

The graph is the single source of truth; the live tutor never reasons over raw
transcripts. Full design: [`docs/DESIGN.md`](./docs/DESIGN.md).

## Architecture

```mermaid
flowchart LR
  subgraph Client
    UI["React + React&nbsp;Flow<br/>graph viz · chat · &quot;consolidate now&quot;"]
  end
  subgraph Backend["FastAPI backend (Engram core)"]
    direction TB
    API["HTTP API<br/>/ingest /recall /consolidate /graph /tutor"]
    REC["Recall<br/>(hot path, no LLM)"]
    KEEP["Memory Keeper<br/>extract→link→merge→resolve→decay→prune"]
    API --> REC
    API --> KEEP
  end
  DB[("Postgres + pgvector<br/>nodes · edges · evidence<br/>events · audit · mastery_history")]
  LLM["OpenRouter<br/>(OpenAI-compatible)<br/>tutor · extractor · reflector"]
  EMB["Embeddings<br/>local hashing (default)<br/>or hosted /embeddings"]

  UI -->|REST| API
  REC --> DB
  KEEP --> DB
  KEEP -->|batched extraction| LLM
  API -->|tutor turn| LLM
  REC --> EMB
  KEEP --> EMB
```

Dependencies point inward: `core/` (pure domain — Protocols + dataclasses) is
imported by `adapters/` (Postgres, OpenRouter, in-memory) and `app/` (FastAPI +
composition root); the core imports none of them. Swapping a database, a model,
or a host is an adapter change, never a core change.

## Quick start (Docker)

```bash
cp .env.example .env
# Optional: paste an OpenRouter key into OPENROUTER_API_KEY to enable the Keeper
# extractor + tutor replies. Everything else (ingest/recall/graph) works without it.
docker compose up --build
```

- Frontend (graph + chat + consolidate): http://localhost:5173
- Backend API: http://localhost:8000  (`GET /health` → `{"status":"ok","db":"ok"}`)
- The `db` service applies [`migrations/0001_engram_schema.sql`](./migrations/0001_engram_schema.sql) on first init.

Try it without the UI:

```bash
curl -s -XPOST localhost:8000/ingest -H 'content-type: application/json' \
  -d '{"learner_id":"alice","events":[{"type":"utterance","text":"I keep messing up the chain rule"}]}'
curl -s -XPOST localhost:8000/consolidate -H 'content-type: application/json' -d '{"learner_id":"alice"}'  # needs a key
curl -s "localhost:8000/graph?learner_id=alice"
```

## The ablation (the "it gets better" proof)

A deterministic eval — no key, no DB — runs a scripted multi-session learner
through Engram's memory vs. a naive "dump the last N raw events" baseline:

```bash
python -m eval.run
```

> With memory, the tutor re-explained mastered material **100% less** (0% vs 100%)
> and recalled prior-session context **3/3** times vs. the baseline's **2/3** —
> because the Keeper synthesized a durable, decaying mastery signal while the
> baseline's evidence aged out of the context window.

## Run the tests / develop locally (no Docker)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db          # or a local Postgres 16 + pgvector
export DATABASE_URL=postgresql://engram:engram@localhost:5432/engram
pytest -q                        # storage tests use the DB; live LLM test auto-skips
python -m uvicorn engram.app.main:app --reload
```

Tip: `ENGRAM_STORAGE_BACKEND=memory` runs the whole API on an in-process store
with zero external services (handy for a quick demo of the graph loop).

## API

See [`docs/API.md`](./docs/API.md). Endpoints: `/health`, `/llm-ping`, `/ingest`,
`/recall`, `/consolidate`, `/consolidate-sweep`, `/graph`, `/audit`, `/tutor/turn`.

## Project layout

```
src/engram/
  core/        # pure: Protocols (Host/Storage/LLM) + dataclasses + Recall + Keeper + Service
  adapters/
    storage/   # postgres.py (asyncpg + pgvector) · memory.py (in-process twin)
    llm/        # openrouter.py (chat) · embeddings.py (local hashing | hosted)
    host/       # text_tutor.py (the demo host adapter)
  app/         # FastAPI app + composition root
migrations/    # 0001_engram_schema.sql
frontend/      # React + React Flow viz (graph · chat · consolidate)
eval/          # deterministic ablation harness
tests/         # contracts, fakes, live-DB + logic tests
```

## Transitioning to Alibaba Cloud

The POC is deliberately built so the hackathon's "runs on Alibaba + calls Alibaba
services" path is a swap, not a rewrite:

- **LLM** — `adapters/llm/openrouter.py` is just the OpenAI SDK pointed at a
  base URL. Alibaba Model Studio (DashScope) is *also* OpenAI-compatible: set
  `OPENROUTER_BASE_URL` to the DashScope compatible endpoint, swap the key + model
  slugs (e.g. `qwen-*`). No code change.
- **Database** — plain Postgres + `pgvector`; lifts onto **Alibaba RDS for
  PostgreSQL / PolarDB** (both support pgvector). The migration applies unchanged.
- **Compute** — the backend `Dockerfile` runs on **ECS** or **SAE** as-is.

## License

MIT — see [`LICENSE`](./LICENSE).
