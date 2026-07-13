# Engram — how it works & SDK guide

Engram is an **in-process learner-memory library**. A host app (tutor, notes,
quizzes) feeds it learning events; Engram maintains a per-learner knowledge
graph and returns a token-budgeted recall block for the next turn.

For internals (ports, Keeper phases, schema), see [ARCHITECTURE.md](ARCHITECTURE.md).
For the original product vision, see [DESIGN.md](DESIGN.md).

---

## How it works

```text
  Host turn                    Offline / async
  ─────────                    ───────────────
  log_turn / ingest  ──►  pending events
                                │
                         consolidate / consolidate_soon
                                │
                                ▼
                         knowledge graph
                         (nodes, edges, evidence)
                                │
  recall(query, budget) ◄───────┘
       │
       ▼
  text_block (+ subgraph) → inject into tutor prompt
```

1. **Ingest** — append `LearningEvent`s (utterances, tutor explanations, notes,
   quiz outcomes). They sit as pending evidence until consolidation.
2. **Consolidate (Keeper)** — LLM-backed offline pass: extract concepts, link,
   merge duplicates, decay/prune. Expensive work stays off the live turn.
3. **Recall** — embed the query, score nodes (recency / importance / relevance),
   walk edges, fill a token budget. Returns a prompt-ready `text_block` plus a
   typed subgraph. No chat LLM on this path.

The graph is the source of truth. The live tutor should not re-read raw chat
history for long-term memory.

---

## Install

```bash
pip install "engram @ git+https://github.com/yfshaikh/qwen.git@engram-poc"
# or a feature branch, e.g. @consumer-sdk
```

Requires Python 3.12+, Postgres with pgvector, and the usual model/API keys
(see root [README.md](../README.md)).

Public imports (stable):

```python
from engram import (
    Engram, EngramHost, DisabledEngram,
    LearningEvent, Node, Edge, Evidence,
    NodeType, EdgeType, EvidenceKind,
    RecallResult, Subgraph, ScoredNode,
    GraphView, GraphNode, GraphEdge, AuditRow,
    ConsolidationReport,
)
```

Prefer `engram` top-level. Treat `engram.core.*` / `engram.adapters.*` as
internal unless you are extending Engram itself.

---

## Using the SDK (`EngramHost`)

`EngramHost` is the embedding runtime. Construction never raises; `start()` is
where connect failures surface (logged once, then latched disabled).

### Lifespan

```python
from engram import EngramHost

host = EngramHost.from_env(
    database_url=os.environ["ENGRAM_DATABASE_URL"],
    model_extractor="qwen/qwen3.5-27b",
    model_reflector="qwen/qwen3.5-27b",
    model_embedder="text-embedding-3-small",
    model_tutor="qwen/qwen3.5-27b",
    _env_file=None,  # optional: ignore cwd .env; pass secrets via env/kwargs
)

# FastAPI example
@asynccontextmanager
async def lifespan(app: FastAPI):
    await host.start()   # opens pool; False => memory disabled for this process
    try:
        yield
    finally:
        await host.aclose()  # drains consolidate_soon / log_* tasks, closes pool
```

| API | Role |
|---|---|
| `host.enabled` | `True` after a successful `start()` |
| `host.memory` | Live `Engram` **or** `DisabledEngram` — never `None` |
| `await host.start()` | Connect; idempotent while live; latches on failure |
| `await host.aclose()` | Cancel owned tasks, close pool, allow restart |

When disabled, every memory verb returns typed empties and does not raise.
Call sites need no `if eng is None` guards.

### Log a tutor turn

```python
await host.log_turn(
    learner_id,
    user_text=user_text,
    tutor_reply=reply,
    refs={"lesson_id": lesson_id},
)
```

Builds utterance + tutor_explanation events, skips blanks, shields the write,
never raises into your turn. Also: `log_quiz`, `log_note`.

### Consolidate after a session

```python
# once per session close (not per turn) — coalesces bursts per learner
host.consolidate_soon(learner_id)

# UI "updating memory" indicator:
host.is_consolidating(learner_id)
```

Or await a full run: `await host.memory.consolidate(learner_id)`.

### Recall into the prompt

```python
res = await host.memory.recall(learner_id, query, budget=600)
prompt_block = res.text_block          # str
nodes = res.subgraph["nodes"]          # list[ScoredNode] (TypedDict / dict)
```

### Direct facade (tests / advanced)

```python
from engram import Engram
eng = Engram(storage=..., llm=..., embedder=...)
await eng.connect()
await eng.ingest([...])
await eng.consolidate(learner_id)
await eng.aclose()
```

Hosts should prefer `EngramHost` so degradation and scheduling stay consistent.

---

## HTTP surface & shared types

### Recommended pattern (host-owned routes)

Keep auth and routing in your app. Import Engram’s **response models** so you
do not re-declare graph/audit shapes:

```python
from engram.integrations.fastapi import (
    MemGraphResponse, MemStatusResponse, MemAuditResponse,
    MemHealthResponse, RecallProbeRequest, RecallProbeResponse,
)
from engram import EngramHost  # via your get_host()

@router.get("/memory/graph", response_model=MemGraphResponse)
async def my_graph(user=Depends(auth)):
    host = get_host()
    if not host.enabled:
        return {"enabled": False, "nodes": [], "edges": []}
    try:
        gv = await host.memory.graph(user.uid)
        return {"enabled": True, "nodes": gv.nodes, "edges": gv.edges}
    except Exception:
        return {"enabled": False, "nodes": [], "edges": []}
```

Same idea for `/status` (`host.is_consolidating`), admin audit/health/recall-probe.

### Optional: mount Engram’s router

```python
from engram.integrations.fastapi import memory_router

app.include_router(memory_router(
    get_host,
    learner_id_dep=my_uid_dep,
    admin_dep=my_admin_dep,   # omit => admin routes are not registered
    prefix="/memory",
))
```

Useful for greenfield hosts. Prefer host-owned handlers when you already have
auth middleware and want the control flow visible in-repo.

### TypeScript types

Generated from the same Pydantic models:

```bash
# in the engram repo
python -m engram.export_types   # → packages/engram-types/index.d.ts
```

**Do not** depend on `github:…#branch&path:…` — npm cannot install a git
subdirectory at a branch reliably. Until `@engram/types` is on the npm registry:

1. Vendor `packages/engram-types/index.d.ts` into your frontend, or
2. Sync from GitHub raw, e.g.

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/yfshaikh/qwen/engram-poc/packages/engram-types/index.d.ts" \
  -o src/types/engram-types.ts
```

See `packages/engram-types/README.md`.

---

## Environment

| Variable | Purpose |
|---|---|
| `ENGRAM_DATABASE_URL` / `DATABASE_URL` | Postgres + pgvector DSN |
| `OPENROUTER_API_KEY` (or provider keys) | Chat models |
| `OPENAI_API_KEY` | Embeddings (default stack) |
| `ENGRAM_MODEL_*` | Tutor / extractor / reflector / embedder slugs |

`EngramHost.from_env(**kwargs)` lets the host override models and DSN from its
own config file (kwargs outrank env).

---

## Versioning

`engram.__version__` tracks the library (currently `0.1.0`). Pin the git ref
your host installs (`@engram-poc`, a release tag, etc.) and bump intentionally
when you take SDK changes.
