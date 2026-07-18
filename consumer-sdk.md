# Engram — how it works & SDK guide

Engram is an **in-process learner-memory library**. A host app (tutor, notes,
quizzes) feeds it learning events; Engram maintains a per-learner knowledge
graph and returns a token-budgeted recall block for the next turn.

For internals (ports, Keeper phases, schema), see [ARCHITECTURE.md](docs/ARCHITECTURE.md).
For the original product vision, see [DESIGN.md](docs/DESIGN.md).

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
2. **Consolidate (Keeper)** — LLM-backed offline pass, split into focused
   calls: extract entities (anchored on the graph's existing labels so the
   same concept is never re-minted under a new name), link/merge, attribute
   assessment evidence to the ONE concept being assessed, infer relations over
   the final labels, then decay/prune. Expensive work stays off the live turn.
3. **Recall** — embed the query, score nodes (recency / importance / relevance),
   walk edges, fill a token budget. Returns a prompt-ready `text_block` plus a
   typed subgraph. No chat LLM on this path.

Optionally, **seed** each learner's graph from your curriculum first (see
"Seeding a curriculum ontology" below) — then concepts and prerequisite edges
come from your course structure, and consolidation only updates the learner's
mastery over them.

The graph is the source of truth. The live tutor should not re-read raw chat
history for long-term memory.

---

## Install

```bash
pip install "engram @ git+https://github.com/yfshaikh/qwen.git@engram-poc"
# or a feature branch, e.g. @consumer-sdk
```

Requires Python 3.12+, Postgres with pgvector, and the usual model/API keys
(see [README.md](README.md)).

### Database setup (one file)

[`migrations/schema.sql`](migrations/schema.sql) is the consolidated,
idempotent schema — apply it once to any Postgres with the `vector` extension
available:

```bash
psql "$ENGRAM_DATABASE_URL" -f migrations/schema.sql
# or without a checkout:
curl -fsSL https://raw.githubusercontent.com/yfshaikh/qwen/engram-poc/migrations/schema.sql \
  | psql "$ENGRAM_DATABASE_URL"
```

Notes: embedding columns are `vector(1024)` — this must match your
`ENGRAM_MODEL_EMBEDDER`'s dimension (`ENGRAM_EMBEDDING_DIM`). The two
`engram_voice_*` tables are optional host-layer session storage; harmless if
unused. The numbered `migrations/000N_*.sql` files are the incremental history
this file consolidates — fresh installs don't need them, and re-applying
`schema.sql` over an existing Engram DB is a no-op.

Public imports (stable):

```python
from engram import (
    Engram, EngramHost, DisabledEngram,
    LearningEvent, Node, Edge, Evidence,
    NodeType, EdgeType, EvidenceKind,
    RecallResult, Subgraph, ScoredNode,
    GraphView, GraphNode, GraphEdge, AuditRow,
    ConsolidationReport,
    ConceptOntology, OntologyConcept, OntologyEdge, OntologyError,
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

### Seeding a curriculum ontology

If your app already has a concept map (a course's concepts + prerequisite
edges, a topic tree), hand it to Engram instead of letting the LLM re-derive
it per learner. Seeded graphs switch extraction to **closed-vocabulary** mode:
the extractor classifies events into *your* concepts (off-list mentions are
dropped to the audit log, never invented), relations come from the curriculum
only, and consolidation focuses on updating mastery.

```python
from engram import ConceptOntology, OntologyConcept, OntologyEdge

ontology = ConceptOntology(
    concepts=[
        OntologyConcept(id="c-slope", label="Slope", summary="rise over run"),
        OntologyConcept(id="c-sif", label="Slope-intercept form"),
    ],
    # DIRECTION: source must be understood BEFORE target.
    # A host row {concept: C, prerequisite: P} ("C requires P")
    # becomes OntologyEdge(source=P, target=C).
    # type defaults to EdgeType.PREREQUISITE; strings ("part_of") are
    # coerced to the enum at construction — junk raises ValueError there.
    edges=[OntologyEdge(source="c-slope", target="c-sif")],
)

# fire-and-forget at session/course start — owned by the host process,
# survives the request; consolidation awaits any in-flight seed
host.seed_soon(learner_id, ontology)
host.is_seeding(learner_id)              # UI indicator
# or await it directly:
await host.memory.seed_ontology(learner_id, ontology)
# -> {"inserted": N, "updated": N, "edges": N}
```

Semantics worth knowing:

- **Validated at the boundary** (`OntologyError`): unique concept ids, edge
  endpoints must exist, one edge per undirected pair, per-edge-type acyclicity.
- **Idempotent + atomic.** Re-seeding upserts labels/summaries/embeddings by
  your stable `id` (stored as `external_id`) and replaces that ontology's
  edges — it **never touches mastery**, so re-seeding after a curriculum edit
  is safe mid-course.
- **Seeded nodes are exempt from pruning and dedup** — the curriculum is not
  the LLM's to forget or merge.
- Seeding needs only the **embedder** (no chat LLM) — it embeds concept
  text, so it's cheap and fast.
- **Scoping is by `learner_id`.** Engram has no course concept; to keep one
  graph per course, compose the id host-side: `learner_id = f"{uid}:{course_id}"`.
- `ontology=None` learners (never seeded) run today's dynamic extraction —
  the two modes coexist per learner.

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

### Full verb reference (`host.memory.*`)

Every verb exists on both `Engram` and `DisabledEngram` (typed empties when
disabled — no `None` guards needed):

| Verb | Returns | Notes |
|---|---|---|
| `ingest(events)` | `None` | append `LearningEvent`s as pending |
| `recall(learner, query, budget)` | `RecallResult` | `text_block` + scored subgraph; no chat LLM |
| `consolidate(learner)` | `ConsolidationReport` | the Keeper pass; per-learner advisory lock |
| `seed_ontology(learner, ontology)` | `dict` | see above |
| `repair_merges(learner)` | `dict` | admin: retroactively merge duplicate nodes on an existing graph |
| `graph(learner, focus=None)` | `GraphView` | full graph for UI; `focus` filters to a node + neighbors |
| `audit(learner, since, limit)` | `list[AuditRow]` | Keeper decision log (merges, drops, contradictions) |
| `events(learner, limit)` | `list[LearningEvent]` | raw event history |
| `health()` | `bool` | storage reachability |
| `create_voice_session` / `append_voice_turn` / `end_voice_session` / `list_voice_sessions` / `list_voice_turns` | ids / lists | optional voice-session store for hosts that persist spoken turns |

### Insights (read-only analytics)

`engram.insights.Insights` wraps aggregation queries over the same graph —
nothing here writes:

| Method | Answers |
|---|---|
| `summary(learner)` | node/evidence counts, mastery distribution |
| `mastery_timeline(learner, ...)` | mastery over time per concept |
| `hotspots(learner, k)` | weakest / most-struggled concepts |
| `activity(learner, days)` | events per day |
| `review_queue(learner, k)` | what to review next (decay-aware) |
| `blockers(learner, ...)` | low-mastery concepts that gate others via prerequisite edges |

The standalone service exposes these at `GET /insights/*` (summary,
mastery-timeline, hotspots, activity, review-queue, blockers).

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

### Or: run Engram as a standalone service

`uvicorn engram.app.main:app` serves the full HTTP surface (this is what the
`web/` console talks to). **No auth is built in** — put it behind your own
gateway if exposed. Endpoints:

| Route | Purpose |
|---|---|
| `GET /health` | liveness + storage check |
| `POST /add` | ingest events (mem0-style alias) |
| `POST /recall` | recall for a learner/query/budget |
| `POST /consolidate` | run the Keeper now |
| `GET /graph` · `GET /history` · `GET /audit` · `GET /events/stream` | graph, mastery history, audit log, SSE event stream |
| `POST /chat` | built-in demo tutor (SSE) |
| `GET /memory/status` | consolidating? node counts |
| `POST /admin/repair-merges` | retroactive duplicate merge |
| `GET /insights/*` | summary, mastery-timeline, hotspots, activity, review-queue, blockers |
| `/eval/*` | eval-run launcher/browser (dev tooling; gate with `ENGRAM_EVAL_UI`) |

### TypeScript types

Generated from the same Pydantic models:

```bash
# in the engram repo
python tools/export_types.py   # → packages/engram-types/index.d.ts
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
| `OPENROUTER_API_KEY` (+ `OPENROUTER_BASE_URL`) | Chat provider (any OpenAI-compatible endpoint) |
| `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`) | Embeddings (default stack) |
| `CEREBRAS_API_KEY` (+ `CEREBRAS_BASE_URL`) | **Optional** 429-fallback chat provider — used only when the primary exhausts retries on a rate limit (e.g. a daily token cap); never load-balanced |
| `ENGRAM_MODEL_TUTOR/EXTRACTOR/REFLECTOR/EMBEDDER` | Role → model slugs (required) |
| `ENGRAM_MODEL_STUDENT/JUDGE` | Optional eval-role overrides (judge falls back to the reflector's model — set it to something cheap) |
| `ENGRAM_TEMPERATURE_<ROLE>` | Optional per-role temperature (e.g. `ENGRAM_TEMPERATURE_EXTRACTOR=0`; unset = provider default) |
| `ENGRAM_EVAL_PRICE_IN_PER_M` / `_OUT_PER_M` | Token prices so eval runs can meter cost / trip `--budget-usd` |

`EngramHost.from_env(**kwargs)` lets the host override models and DSN from its
own config file (kwargs outrank env).

---

## Versioning

`engram.__version__` tracks the library (currently `0.1.0`). Pin the git ref
your host installs (`@engram-poc`, a release tag, etc.) and bump intentionally
when you take SDK changes.
