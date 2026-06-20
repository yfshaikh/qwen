# Engram — Architecture

> **Living document.** Unlike `DESIGN.md` (the original vision/spec), this records
> the architecture **as actually built**, decision by decision, and is updated as
> each phase lands. Diagrams are intentionally small and scoped — one per system
> or subsystem — so each is easy to hold in your head.
>
> **Status legend:** ✅ built & tested · 🟡 designed, not yet built · ⬜ future phase
>
> | Phase | Area | Status |
> |---|---|---|
> | 0 | Foundations (core, ports, schema, adapters, facade) | ✅ |
> | 1 | Ingest + Recall (read path) | ✅ |
> | 2 | Memory Keeper (`consolidate`) | ✅ |
> | 3 | Text tutor (`/chat`) | ⬜ |
> | 4 | React console | ⬜ |
> | 5 | Eval + polish | ⬜ |

---

## 1. System overview

Engram is an **app-agnostic learner-memory core**: a host feeds it generic
`LearningEvent`s; an offline **Keeper** distils them into a knowledge graph; a fast
**Recall** reads a token-budgeted subgraph for the live tutor. The graph is the
single source of truth — the tutor never reasons over raw history.

```mermaid
flowchart LR
    Host["Host app<br/>(voice tutor, notes, quizzes)"]
    subgraph Core["Engram core (app-agnostic)"]
        Ingest["ingest()<br/>append events"]
        Keeper["Keeper<br/>consolidate() — offline"]
        Graph[("Knowledge graph<br/>Postgres + pgvector")]
        Recall["recall()<br/>token-budgeted subgraph"]
    end
    Host -- "LearningEvent[]" --> Ingest --> Graph
    Keeper -- "extract→link→merge→<br/>resolve→decay→prune" --> Graph
    Graph --> Keeper
    Host -- "recall(learner, query, budget)" --> Recall
    Graph --> Recall
    Recall -- "text_block + subgraph" --> Host
```

**Two agents over one graph.** Expensive reasoning is **offline** in the Keeper
(amortized per "sleep"); the live turn is one cheap Recall (no LLM on the hot
path). See [DESIGN.md](DESIGN.md) §0 for the rationale.

---

## 2. Layering (ports & adapters)

The asset is the **core**; everything provider- or transport-specific is an
**adapter** or **app glue**. `core/` imports nothing from `adapters/` or `app/`.

```mermaid
flowchart TD
    subgraph app["app/ (composition + HTTP — throwaway glue)"]
        Settings["Settings (config)"]
        Facade["Engram facade<br/>from_env / ingest / recall / consolidate"]
    end
    subgraph core["core/ (pure — no infra imports)"]
        Models["models (Node, Edge, Evidence,<br/>LearningEvent, RecallResult, …)"]
        Ports["ports (Protocols):<br/>LLMPort · EmbedderPort · StoragePort · HostPort"]
        Recall["recall (§4.4 algorithm)"]
        Keeper["keeper (consolidate planner)"]
        Tokens["tokens (counter)"]
    end
    subgraph adapters["adapters/ (concrete impls)"]
        LLM["OpenAICompatibleLLM<br/>(OpenRouter → DashScope later)"]
        Emb["OpenAIEmbedder<br/>(→ DashScope later)"]
        PG["PostgresStorage<br/>(asyncpg + pgvector)"]
        Seed["seed (YAML loader)"]
    end
    Facade --> Ports
    Recall --> Ports
    Keeper --> Ports
    LLM -.implements.-> Ports
    Emb -.implements.-> Ports
    PG -.implements.-> Ports
    Facade --> LLM & Emb & PG
    core --> Models
```

**Why split `LLMPort` and `EmbedderPort`?** OpenRouter (chat) has no embeddings
endpoint, so embeddings go to OpenAI. Separate ports let each swap to DashScope
independently when we move to Alibaba — a config + preset change, no core edits.

---

## 3. Data model

Six learner-scoped tables (`migrations/0001_engram_schema.sql`). Bounded type sets
keep LLM cost down and the graph legible — the Keeper cannot invent types.

```mermaid
erDiagram
    engram_nodes ||--o{ engram_edges : "source/target"
    engram_nodes ||--o{ engram_evidence : "has"
    engram_nodes ||--o{ engram_mastery_history : "snapshots"
    engram_events }o--|| engram_audit : "traces"
    engram_nodes {
        uuid id PK
        text learner_id
        text type "concept|preference|goal"
        text label
        real mastery "0..1 EWMA"
        real confidence
        real salience "decays; bumped on touch"
        vector embedding "1024 dims"
        timestamptz forgotten_at "soft-delete"
    }
    engram_edges {
        uuid id PK
        uuid source_id FK
        uuid target_id FK
        text type "prerequisite|relates_to|part_of"
    }
    engram_evidence {
        uuid id PK
        uuid node_id FK
        text kind "quiz_correct|struggle|demonstrated|…"
        real importance
    }
    engram_events {
        uuid id PK
        text learner_id
        jsonb signals "escape hatch (BKT/FSRS)"
        timestamptz consolidated_at "watermark; NULL=pending"
    }
```

Three append-only streams give observability: `engram_events` (in), `engram_audit`
(every Keeper/Recall op + rationale), `engram_mastery_history` (per-node
trajectories). `embedding` is `vector(1024)` — the single source of truth for the
dimension; must match `ENGRAM_EMBEDDING_DIM`.

---

## 4. Provider seam (Phase 0) ✅

One `OpenAICompatibleLLM` (chat) + one `OpenAIEmbedder`, wired by `Settings`'
role→model map. The Alibaba switch is a base-url/key change plus a DashScope
preset — no core changes.

```mermaid
flowchart LR
    subgraph roles["role → model (Settings)"]
        tutor & extractor & reflector --> LLMc["OpenAICompatibleLLM"]
        embedder --> EMBc["OpenAIEmbedder"]
    end
    LLMc -->|"OpenRouter now /<br/>DashScope later"| ChatAPI["/v1/chat/completions"]
    EMBc -->|"OpenAI now /<br/>DashScope later"| EmbAPI["/v1/embeddings (1024d)"]
```

---

## 5. Ingest (Phase 1) ✅

Append-only, no LLM, no embedding — the cheap write path. Validates each event,
inserts in one transaction with `consolidated_at = NULL` (the Keeper's queue).

```mermaid
flowchart LR
    H["host"] -->|"add() / ingest(events)"| V{"valid?<br/>learner_id + type"}
    V -- no --> Err["ValueError<br/>(nothing written)"]
    V -- yes --> Tx["insert_events()<br/>one transaction"]
    Tx --> E[("engram_events<br/>consolidated_at = NULL")]
```

---

## 6. Recall (Phase 1) ✅

The §4.4 read path: vector-seed → bounded graph hop → score → token-budget fill.
**No LLM on the hot path** (one embedding + a vector query + a bounded traversal).
The hybrid (vector-seed + graph expansion) is the efficiency consensus from the
2026 GraphRAG/HippoRAG literature — see [DESIGN.md](DESIGN.md) §12 / MVP spec §12.

```mermaid
sequenceDiagram
    participant H as Host
    participant R as Recall
    participant Emb as Embedder
    participant S as Storage (pgvector)
    H->>R: recall(learner, query, budget)
    R->>Emb: embed(query)
    Emb-->>R: query_vec
    R->>S: vector_search(learner, query_vec, k)
    S-->>R: seed nodes (forgotten excluded)
    R->>S: get_edges + get_nodes (1–2 hops, fanout-capped)
    S-->>R: neighbor nodes + edges
    R->>S: top_evidence(node_ids)
    S-->>R: evidence per node
    Note over R: score = w_r·salience + w_i·importance + w_v·relevance<br/>relevance = cosine(query_vec, node.embedding) in Python<br/>greedy fill to token budget
    R-->>H: RecallResult { text_block, subgraph(+sub-scores) }
```

Scoring weights (`w_r/w_i/w_v=0.3/0.3/0.4`) and traversal params (`seed_k/hops/
fanout`) live in `Settings`, env-overridable so the eval harness can sweep them.

---

## 7. Memory Keeper — `consolidate()` (Phase 2) ✅

The core IP: turns pending events into graph. **Plan, then commit** — a *pure*
planner produces a `ConsolidationPlan`; the only DB writes happen in one atomic
`apply_consolidation`. Crash mid-plan → nothing written → safe re-run.

```mermaid
flowchart TD
    Start["consolidate(learner)"] --> Lock{"advisory lock<br/>acquired?"}
    Lock -- "held" --> Skip["report skipped=True"]
    Lock -- "yes" --> Read["read pending events<br/>+ live nodes"]
    Read --> Empty{"any pending?"}
    Empty -- no --> Done0["empty report"]
    Empty -- yes --> Plan
    subgraph Plan["PLAN (pure — LLM/embedder, no DB writes)"]
        Ex["extract<br/>(1 batched LLM call)"] --> Lk["link/merge<br/>(vectors; LLM if ambiguous)"]
        Lk --> Rs["resolve<br/>(EWMA + contradictions)"]
        Rs --> Dp["decay + prune<br/>(soft-delete)"]
        Dp --> Sn["snapshot<br/>(mastery_history + watermark)"]
    end
    Plan --> Commit["apply_consolidation(plan)<br/>ONE transaction"]
    Commit --> Report["ConsolidationReport"]
```

**Link/merge decision** (vectors first, LLM only in the ambiguous band):

```mermaid
flowchart LR
    C["candidate concept"] --> M{"max cosine sim<br/>to live nodes"}
    M -- "≥ τ_high (0.86)" --> A["attach evidence<br/>(dedup)"]
    M -- "≤ τ_low (0.72)" --> N["create new node"]
    M -- "between" --> J["reflector confirm<br/>(LLM y/n)"]
    J -- yes --> A
    J -- "no / LLM fail" --> N
```

**Mastery (EWMA).** Each evidence kind → an observation (`quiz_correct=1.0`,
`quiz_wrong=0.0`, `demonstrated=0.9`, `struggle=0.2`; `note/explained/asked_about`
skip), overridden by explicit event `signals` (signal-greedy). Then
`mastery = α·obs + (1−α)·mastery_old` (α=0.3). Confidence rises on agreement, dips
on conflict (which logs a `resolve_contradiction` audit row). **Forgetting:**
untouched nodes `salience *= decay^Δt`; below `prune_floor` → `forgotten_at` set.

Idempotent by construction: the watermark advances only inside the committed
transaction; the advisory lock serializes per-learner runs. Full detail in the
[Phase 2 spec](superpowers/specs/2026-06-17-engram-phase-2-memory-keeper-design.md).

---

## 8. Public API surface

mem0-style ergonomics over typed depth. The library is the primary surface; the
FastAPI app (Phase 3) re-exposes the same verbs over HTTP for non-Python hosts.

| Verb | Alias | Phase | What |
|---|---|---|---|
| `ingest(events)` | `add` | 1 ✅ | append `LearningEvent`s |
| `recall(learner, query, budget)` | `search` | 1 ✅ | token-budgeted subgraph |
| `consolidate(learner)` | — | 2 ✅ | run the Keeper |
| `graph(learner, focus?)` | — | 4 ⬜ | render-ready view |

```python
eng = Engram.from_env()      # wires PostgresStorage + OpenRouter LLM + OpenAI embedder
await eng.connect()
await eng.add(events, ...)    # ingest
ctx = await eng.recall("derivatives", learner_id="alice", budget=800)
report = await eng.consolidate(learner_id="alice")   # Phase 2
```

---

## 9. Host/tutor boundary — tools live in the tutor, not in Engram

A strict line the whole design rests on: **Engram is memory, not the agent that
acts.** Tools (view the page, read its HTML, point at an element, render a slide),
perception, STT/TTS, and UI are **host/tutor** concerns. Engram never knows what a
"page" or "PDF" is — it only stores events and serves recalled context. This is
what keeps the memory core droppable into *any* host.

**Decision (2026-06-17):** the tutor ships as a **separate package** depending on
`engram`, with its own **tool plugin interface** (register tools like
`view_page` / `read_html` / `point`). `engram` stays pure memory.

```mermaid
flowchart LR
    subgraph tutorpkg["tutor host package (separate; Phase 3+)"]
        Tools["tools: view_page / read_html / point"]
        Agent["tutor agent (the LLM turn)"]
        Tools --> Agent
    end
    subgraph engrampkg["engram package (memory core)"]
        API["recall / ingest / consolidate"]
    end
    Agent -- "recall(learner, query)" --> API
    API -- "memory context" --> Agent
    Agent -- "emit LearningEvent[]" --> API
```

Flow: *a tool perceives → the tutor reasons (with Engram's recalled memory in its
prompt) → the tutor emits events → Engram remembers.* Tools feed the tutor; the
tutor feeds Engram. Adding a new perception tool is a tutor change, never an
Engram change. (clicky, if used as a host, plugs in exactly here — via the HTTP
service since its backend is a non-Python Cloudflare Worker.)

---

## 10. Deployment & the Alibaba switch (future)

Backend (FastAPI + Keeper cron) targets Alibaba ECS/SAE; DB → Alibaba
RDS/PolarDB (pgvector); inference → DashScope. All built-for via the provider seam
(§4) — no core changes, a config + DashScope-preset swap. Detail lands here when
Phase 5 deployment is built.
