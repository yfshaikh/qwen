# Engram

App-agnostic memory core for AI tutors: turns a stream of generic learning
events into a living knowledge graph of a learner, maintained by an offline
"Memory Keeper" agent and read by a fast, token-budgeted Recall.

See `docs/ARCHITECTURE.md` for the architecture as actually built, and
`docs/DESIGN.md` for the original vision.

## What's here

- **`src/engram/`** — the memory core (`ingest` / `recall` / `consolidate` /
  `graph`) plus a thin FastAPI service that re-exposes it over HTTP.
- **`web/`** — a React + React Flow **console**: chat the tutor, click
  **Consolidate**, and watch the learner's knowledge graph form.

## Embedding Engram

Host apps embed Engram in-process via `EngramHost` and (optionally) mount the
auth-injectable FastAPI router:

```python
from engram import EngramHost
from engram.integrations.fastapi import memory_router

host = EngramHost.from_env(database_url=..., model_extractor=..., ...)
# FastAPI lifespan: await host.start()  /  await host.aclose()
app.include_router(memory_router(lambda: host, learner_id_dep=my_uid_dep, admin_dep=my_admin_dep))

# per turn:
await host.log_turn(uid, user_text=q, tutor_reply=a, refs={"lesson_id": lid})
host.consolidate_soon(uid)
# recall context: (await host.memory.recall(uid, q, budget=600)).text_block
```

See [`docs/consumer-sdk.md`](docs/consumer-sdk.md) for the consumer-sdk contract
(local design notes live under `docs/superpowers/` and are not published).

## Prerequisites

- Python 3.12
- Docker (runs a local pgvector Postgres)
- Node 18+ (for the `web/` console)

---

## 1. Backend — database + service

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then fill in real keys (see below)
docker compose up -d          # local pgvector on :5432; auto-applies migrations/
```

### Environment variables (`.env`)

**Required** (no default — the service won't start without these):

| Var | What |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter key — chat models (tutor / extractor / reflector) |
| `OPENAI_API_KEY` | OpenAI key — embeddings |
| `DATABASE_URL` | Postgres DSN. For the local Docker DB: `postgresql://engram:engram@localhost:5432/engram` |
| `ENGRAM_MODEL_TUTOR` | chat model for the live tutor turn (e.g. `qwen/qwen-2.5-72b-instruct`) |
| `ENGRAM_MODEL_EXTRACTOR` | chat model for the Keeper's extraction pass |
| `ENGRAM_MODEL_REFLECTOR` | chat model for the Keeper's merge / contradiction checks |
| `ENGRAM_MODEL_EMBEDDER` | embedding model (e.g. `text-embedding-3-small`) |

**Optional** (sensible defaults — see `src/engram/app/config.py`):

| Var | Default | What |
|---|---|---|
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | chat base URL (swap for DashScope, etc.) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | embeddings base URL |
| `ENGRAM_EMBEDDING_DIM` | `1024` | embedding dim — **must match** the DB `vector(1024)` column |
| `ENGRAM_RECALL_*` | see config | recall scoring weights + traversal (eval sweeps) |
| `ENGRAM_KEEPER_*` | see config | consolidation thresholds (eval sweeps) |
| `ENGRAM_AUDIT_*` | see config | audit poll interval / page size |

The Docker container (`docker-compose.yml`) provisions Postgres with user/password/db
all `engram` on port `5432` and auto-runs the SQL in `migrations/` on first boot, so
the `DATABASE_URL` above works out of the box.

### Run the service

```bash
.venv/bin/uvicorn engram.app.main:app --port 8050 --reload
```

`--reload` restarts the server when you edit code; without it a running process keeps
the old code in memory (drop it in production).

Routes: `GET /health`, `POST /add`, `POST /recall`, `POST /consolidate`,
`GET /audit`, `GET /events/stream`, `POST /chat` (SSE), `GET /graph`.

---

## 2. Web console (`web/`)

The console drives the running service — chat the tutor, watch raw events accrue,
then hit **Consolidate** to watch the Keeper turn the conversation into a graph.

```bash
cd web
npm install
npm run dev                   # http://localhost:5173
```

With the service running on `:8050`, open http://localhost:5173, send a message,
then click **Consolidate**. The dev server proxies the API to `http://localhost:8050`
— point it elsewhere with `VITE_API_BASE`:

```bash
VITE_API_BASE=http://localhost:8011 npm run dev
```

### Example flows

The empty console shows clickable starter flows — click a prompt to send it, run a
few turns, then **Consolidate**. Or type your own:

- **Calculus (limits → continuity):** "What is a limit in calculus? Keep it to two
  sentences." → "How does that connect to continuity?" → "Quiz me: is a function
  with a hole in its graph continuous at the hole?"
- **Spanish basics:** "Teach me how to greet someone in Spanish." → "How do I say
  'I would like a coffee, please'?" → "Quiz me on the greetings you just taught me."
- **Learning preferences:** "I learn best with real-world examples and analogies,
  not formal definitions." → "Explain recursion to me in that style." → "What do
  you remember about how I like to learn?"

Run a flow, hit **Consolidate**, and watch the nodes and edges form.

---

## 3. Eval harness

`src/engram/eval/` runs against the core library directly (no HTTP) to tune recall
config and produce the memory-ON-vs-baseline demo numbers. Scenarios live in
`eval/scenarios/*.yaml`; an LLM "student" authors each scenario's conversation
**once** and freezes it (transcript + consolidated graph) into a committed fixture
under `eval/fixtures/`.

```bash
# 1. Generate (or refresh) a fixture — needs Postgres + API keys (spends LLM calls)
python -m engram.eval gen eval/scenarios/calc-mastery.yaml

# 2. Tune: sweep recall weights against the frozen graph (Tier-1 — embedder only,
#    no chat LLM; replays the committed fixture, so it is cheap + reproducible)
python -m engram.eval sweep eval/scenarios/calc-mastery.yaml \
  eval/fixtures/calc-mastery.json --grid eval/scenarios/calc-mastery.sweep.yaml

# 3. Demo headline: memory ON vs naive baseline, scored by an LLM judge
python -m engram.eval demo eval/scenarios/calc-mastery.yaml eval/fixtures/calc-mastery.json
```

Fixtures are committed so sweeps are reproducible; re-run `gen` to regenerate them
when prompts change. Reports are written to `eval/reports/` (gitignored).

---

## Tests

```bash
pytest                        # backend; Docker DB up for live tests, live-LLM smokes opt-in
cd web && npm test            # console (Vitest)
```

## License

MIT — see `LICENSE`.
