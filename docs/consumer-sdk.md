# Consumer SDK & exported types

**Status:** superseded / implemented (qwen side, 2026-07-11).

This 2026-06-30 wishlist is **implemented** (qwen / Engram side). Local agent
plan/spec notes (not in git): `docs/superpowers/specs/memory-v2/2026-07-11-consumer-sdk-design.md`,
`docs/superpowers/plans/2026-07-11-consumer-sdk.md`.

**Shipped on the qwen / Engram side:** typed top-level exports + `py.typed`,
typed facade returns, `EngramHost` runtime, mountable FastAPI `memory_router`,
and generated TS types. **Marfini consumption** (install from `engram-poc`,
swap glue for `EngramHost` + router) is still pending.

For the embed snippet, see the README **"Embedding Engram"** section.

---

## Historical wishlist (2026-06-30)

The sections below are the original enhancement request, kept for context.
Do not treat them as the live contract — the shipped surface above is authoritative.

### The problem
Engram is consumed as an embedded pip dependency — the host calls the `Engram`
facade in-process. Today the public surface is effectively just that facade; the
data **types are private**, so a consumer that wants typed access, or wants to
expose Engram data over its own HTTP API, has to **replicate Engram's types in
its own code**. In Marfini that meant defining the same shapes twice — once as
Pydantic models in `api/routes/memory_routes.py`, again as TS interfaces in
`frontend/src/modules/memory/types.ts` — both hand-copied from Engram internals.
Every schema change now has to be mirrored in three places.

### Concrete friction (current state)
- **Top-level package exports only `Engram`.** `engram/__init__.py` has
  `__all__ = ["Engram"]`; data classes live in `engram.core.models` and the
  HTTP request/response models in `engram.app.schemas`. There's no blessed
  public path for the return types — consumers reach into internal modules.
- **No `py.typed` marker.** Even when a consumer imports Engram's classes,
  downstream type checkers (mypy/pyright) treat the package as untyped, so no
  type information propagates.
- **The facade returns loosely-typed data:**
  - `recall()` → `RecallResult(text_block: str, subgraph: dict[str, Any])` — the
    subgraph (nodes with `score` + `scores{recency,importance,relevance}`, and
    edges) is an untyped dict; consumers reverse-engineer the shape.
  - `graph()` → `GraphView`, whose `nodes`/`edges` are `list[dict]`, not
    `list[Node]`/`list[Edge]`.
  - `audit()` → `list[dict]`.
  So even the typed-looking returns bottom out in dicts.
- **HTTP schemas aren't reusable.** `engram/app/schemas.py` already defines clean
  Pydantic models (`GraphResponse`, `GraphNode`, `GraphEdge`, `GraphEvidence`,
  `AuditRow`, `ReportOut`, …), but they're bound to Engram's own FastAPI app —
  not exported for a host app to mount or reuse as response models.
- **No shared/published TS types.** The console's `web/src/types.ts` mirrors the
  same shapes, but there's nothing a JS/TS consumer can install or codegen from,
  so the interfaces get hand-copied a third time.

### Desired direction
A stable, typed, low-friction consumer SDK:

1. **Export public types from the top level + add `py.typed`.** Re-export the
   ingest/return types (`LearningEvent`, `Node`, `Edge`, `Evidence`,
   `RecallResult`, `GraphView`, a typed `Subgraph`/`ScoredNode`, `AuditRow`,
   `ConsolidateReport`, the `*Type` enums) from `engram/__init__.py` so
   `from engram import RecallResult, GraphView, ...` works, and ship a `py.typed`
   marker so those types actually reach consumers' checkers.
2. **Return typed objects, not dicts.** `graph()` → `GraphView` with
   `nodes: list[Node]` / `edges: list[Edge]`; `RecallResult.subgraph` gets a real
   type (`Subgraph{ nodes: list[ScoredNode], edges: list[Edge] }`); `audit()` →
   `list[AuditRow]`. One canonical model set shared by the facade **and** the HTTP
   app — collapse the `core.models` ↔ `app.schemas` duplication (share the core
   models, or generate the Pydantic layer from them).
3. **Ship reusable API building blocks.** So a host never re-declares response
   models: export the Pydantic response models for reuse, and/or provide a
   ready-made, auth-injectable FastAPI `APIRouter` (graph / audit / recall /
   health) the host mounts with its own auth dependency. Marfini's
   `memory_routes.py` would then be a thin auth wrapper, not a re-implementation.
4. **Publish/generate TS types.** Emit an OpenAPI schema from the HTTP app (or
   JSON Schema from the Pydantic models) and generate TS types from it — shipped
   as a small `@engram/types` package or a committed generated file. Kills the
   hand-copied `types.ts`.

### Priority / sizing
- **Cheap, high value:** (1) top-level exports + `py.typed`. Immediately removes
  "import from internals" and gives Python consumers types for free.
- **Medium:** (2) typed facade returns + collapsing the core/app model
  duplication. Touches internals; eval + tests must stay green.
- **Medium:** (4) TS generation from OpenAPI — removes the frontend duplication.
- **Larger:** (3) a mountable, auth-injectable router — best DX, but a bigger
  API-design commitment; do after (1)/(2).

### Motivating example (Marfini)
`api/routes/memory_routes.py` re-declares `GraphResponse` / `GraphNode` /
`GraphEdge` / `GraphEvidence` / `AuditRow` as Pydantic;
`frontend/src/modules/memory/types.ts` re-declares them as TS. With (1)+(2) the
backend imports Engram's models directly; with (4) the frontend imports generated
types; with (3) the whole `memory_routes` graph/audit/recall surface collapses to
mounting Engram's router behind `get_current_user`.
