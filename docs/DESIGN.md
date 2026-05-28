# Engram — a portable memory agent for AI tutors

> **Status:** Design approved, pre-implementation.
> **Date:** 2026-05-26.
> **Purpose of this document:** a self-contained spec + plan for a fresh agent
> starting in a brand-new, empty repository. It assumes no prior conversation.
> Read it top to bottom; it carries all the context, the architecture, and the
> phased build plan. Where a decision must be confirmed against a live service
> at build time, it says so explicitly.

---

## 0. TL;DR

We are building **Engram**: an app-agnostic memory core that turns a stream of
generic *learning events* into a **living knowledge graph of a learner**,
maintained by a background "Memory Keeper" agent and read by a live voice tutor.
It is being built as a submission to the **Qwen Cloud Global AI Hackathon,
Track 1 (MemoryAgent)**, and is deliberately structured so it can later drop
into two existing products (Starnotes and Marfini) as a reusable module.

The spine: **two agents over one graph.**
- **Memory Keeper** (slow, offline, "asleep"): extracts concepts/preferences/
  goals + evidence from events, links/merges them into a graph, resolves
  contradictions, and decays/prunes stale memory. All the expensive reasoning
  lives here, amortized.
- **Recall** (fast, hot path, no LLM): a tutor turn asks for "what matters about
  this learner + this topic right now" and gets a small, token-budgeted
  subgraph. No reasoning on the critical path.

The graph is the single source of truth. The live tutor never reasons over raw
history — the Keeper has already distilled it.

---

## 1. Context

### 1.1 The hackathon

**Qwen Cloud Global AI Hackathon.** Build production-ready agents on Qwen Cloud
(Alibaba Cloud) infrastructure. Prizes: $70,000+ cash + cloud credits, blog
feature, AI Catalyst invite. The hackathon explicitly values "architectural
depth and engineering excellence."

**Track 1 — MemoryAgent (the track we are entering).**
> Build an Agent with persistent memory that autonomously accumulates
> experience, remembers user preferences, and makes increasingly accurate
> decisions across multi-turn, cross-session interactions. Focus on: efficient
> memory storage and retrieval, timely forgetting of outdated information, and
> recalling critical memories within limited context windows.

**Hard submission requirements (all mandatory unless marked optional):**
- Public, open-source repo with a **detectable LICENSE** (visible in the repo's
  About section). → Use a permissive license (MIT/Apache-2.0) at repo root.
- **Proof of Alibaba Cloud deployment:** (a) the backend must be *running* on
  Alibaba Cloud, shown in a short recording, and (b) a link to a **code file in
  the repo that demonstrates use of Alibaba Cloud services/APIs**.
- **Architecture diagram** (Qwen Cloud ↔ backend ↔ database ↔ frontend).
- **~3-minute demo video** (public on YouTube/Vimeo/Facebook).
- **Text description** of features/functionality.
- **Track identifier** (Track 1).
- *Optional:* a blog/social post on the build journey (eligible for a Blog Prize).

### 1.2 Strategic decisions already made (and why)

1. **Fresh repo, not an existing project.** Hackathons generally require the
   project be built during the event. We cherry-pick *specific files* from
   Starnotes (see §2) into this new repo rather than submitting an existing app.
2. **Voice tutor is the demo surface; the memory agent is the substance.** Put
   ~80% of effort into the memory core. The voice tutor is the vehicle that
   makes memory *visible* in a 3-minute video. Do **not** try to ship a complete
   e-learning platform — that's the scope trap.
3. **App-agnostic core.** The memory core is a standalone module with three thin
   ports (host, storage, LLM). Reason: it must later integrate into Marfini, and
   Marfini is a moving target (mid-pivot). A stable core behind a thin event
   seam means Marfini's churn updates an *adapter*, not the brain. It also lets
   us eval the core independently and share one brain across two hosts.
   - **Key principle: agnostic about the _app_ (UI, storage, LLM provider);
     opinionated about the _learning domain_ (concepts, mastery, evidence are
     universal to tutoring).** And **signal-greedy**: the event interface has a
     `signals` escape hatch so a richer host (e.g. Marfini, with BKT/FSRS) can
     hand in better data, which the core uses when present and falls back to its
     own estimators when absent. No effectiveness tax for being agnostic.
4. **Depth/wow comes from the memory architecture, not the table-stakes
   behaviors.** "Tutor remembers your preferences" is what every Track 1 entry
   will demo. Our differentiators (chosen deliberately): a **living knowledge
   graph** (visible, navigable, fused across docs + notes + quizzes) and a
   **two-agent "sleep & reflect"** consolidation loop. The four table-stakes
   behaviors (recall a past struggle, stop over-explaining, learn my style,
   connect across docs) are not four features — they are four *read-patterns
   over the same store*, and fall out for free.
5. **Cost + performance are first-class** (this becomes a real product). The
   two-agent split is the main cost mechanism: expensive reasoning is offline
   and amortized; the live turn is one cheap call. Model **tiering** via the LLM
   port is the #1 cost lever; Qwen now, cheaper models swappable later by config.

### 1.3 Relationship to the two real products

- **Starnotes / `pdf-tool`** (`~/Desktop/Projects/pdf-tool`): a working PDF study
  tool with a **live voice tutor** (push-to-talk over a PDF, STT→vision-LLM→TTS).
  Already uses Qwen (`qwen/qwen3-vl-235b` for lectures). It has a *primitive*
  memory today (see §2.2) that we are upgrading. This is the source of the voice
  host adapter and the demo surface.
- **Marfini / Tamkeen** (`~/Desktop/Projects/Marfini`): a proprietary,
  full learning platform. Not submitted (proprietary; can't be open-sourced).
  It is the *eventual* second host for Engram, and the source of several reusable
  design references (FSRS, React Flow concept maps, a planned StudentSimulator
  eval harness, an openai-agents `AgentRunner` pattern).

---

## 2. Source material to pull from (with paths)

### 2.1 Starnotes voice tutor — port these as the basis of the voice host adapter

The new repo reimplements/ports (not copies wholesale) the voice loop. Reference
files in `~/Desktop/Projects/pdf-tool`:

| File | What to reuse |
|---|---|
| `backend/routers/voice.py` | Push-to-talk WebSocket loop: subprotocol JWT auth, lazy session creation, prefetch-on-PTT-start, sentence-chunked TTS, barge-in/cancel, cost caps, transcript hydration. ~1860 lines; the patterns matter more than the lines. |
| `backend/services/voice/stream.py` | Inline-directive splitter (strips `[NOTE:...]` from the TTS stream). Pattern for structured side-channel events mid-stream. |
| `backend/services/voice/stt.py`, `tts.py` | STT (Groq Whisper) + TTS (OpenAI `gpt-4o-mini-tts`) adapters. Replaceable; behind their own seams. |
| `sql/migrations/0010_voice_sessions.sql`, `0011_voice_notes.sql` | The current memory baseline schema (see §2.2). |
| `frontend/.../lib/voice.ts` (referenced in voice.py comments) | Client mic/PTT/interrupt handling. |

**Important Starnotes architectural facts the adapter must respect:**
- A `voice_sessions` row is per `(user, document)` and **reused** across visits
  (looked up + re-marked active on reconnect; marked `ended` on disconnect).
- Sessions are created **lazily** on first push-to-talk.
- The server **prefetches** turn context (PDF render + history + notes) on
  PTT-start so it overlaps with the user speaking — we reuse this to hide Recall
  latency.
- The system prompt is split into a cacheable stable prefix + a per-turn block
  (OpenRouter/provider prompt caching, ~80% prefix savings). Engram's Recall
  block slots into the per-turn section.

### 2.2 The current Starnotes memory baseline (what we are beating)

Today's "memory" is naive and is exactly the limited-context problem Track 1
asks us to solve well:
- `voice_turns`: raw transcript log (role, transcript, page_number, cost).
- `voice_notes`: tutor-authored margin pins; the **last 20 are dumped** into the
  prompt as a "scratchpad."
- plus the user's own margin `notes`.
- Retrieval = "cram the last N turns + last 20 notes into context." No learner
  model, no semantic retrieval, no importance scoring, no decay, no cross-document
  memory.

The submission narrative: *we replaced last-N-dump with a typed, decaying,
retrieval-scored, cross-document knowledge graph maintained by a reflective
agent.*

### 2.3 Marfini reuse references (design only; do not copy proprietary code)

- **FSRS spaced-repetition** (`Marfini/docs/vocab/FSRS_SPACED_REPETITION.md`) and
  **BKT mastery** (`Marfini/docs/eval/BKT_METRICS.md`): the principled
  mastery/forgetting estimators that can swap in behind Engram's `mastery`
  attribute later. v1 uses EWMA (§4.3).
- **React Flow concept maps** (Marfini course-chat `ConceptsTab`): node/edge
  rendering conventions (solid = prerequisite/linear, dashed = associative). Our
  graph viz mirrors this so the component family ports over.
- **StudentSimulator + eval harness** (`Marfini/docs/planning/NEW_FEATURES.md`
  §1): the design for an LLM-driven scripted learner driving multi-session
  conversations, with layered scoring. We lift this design for §7.
- **AgentRunner** (Marfini course-chat, openai-agents SDK): pattern for an agent
  loop with tool calls + streaming, if we make the Keeper tool-driven.

---

## 3. Architecture overview (the spine)

```
                          ENGRAM CORE (app-agnostic)
  host app ──events──▶ ┌────────────────────────────────────────────┐
  (Starnotes voice,    │  MEMORY KEEPER  (slow, offline, "asleep")    │
   notes, quizzes)     │    extract → link → merge → resolve          │
                       │    contradictions → decay → prune → snapshot │
                       │                 maintains ↓                  │
                       │   KNOWLEDGE GRAPH                            │
                       │   nodes + edges + scored evidence            │
                       │   (Postgres + pgvector)                     │
                       │                 reads ↑                      │
  tutor turn ─recall──▶│  RECALL  → token-budgeted relevant subgraph  │──▶ context
  (voice/text)         │           (no LLM on this path)              │   for the tutor
                       └────────────────────────────────────────────┘
                                         │
                              render-ready {nodes, edges, state} ──▶ React Flow viz
```

### Track 1 criteria → concrete mechanism (no buzzwords)

| Track 1 criterion | Mechanism in Engram |
|---|---|
| Efficient storage & retrieval | Typed graph + pgvector; retrieve a bounded subgraph, not raw logs |
| Timely forgetting | Keeper's decay + prune pass on node salience and evidence scores |
| Recall within limited context | Token-budgeted subgraph assembly scored by recency·importance·relevance |
| Autonomous accumulation + multi-agent | The Keeper reflects/consolidates offline, unprompted |
| Increasingly accurate decisions | Mastery/confidence updates + contradiction resolution change tutor behavior |

---

## 4. Detailed design

### 4.1 Data model

**Fixed, small type sets** — deliberately bounded to control LLM cost and keep
the React Flow view legible. The Keeper is **not** allowed to invent new types.

- **Node types:** `concept` (a knowledge topic touched), `preference` (how the
  learner likes to learn), `goal` (what they're working toward). Misconceptions
  and mastery are *state + evidence on concept nodes*, not separate types.
- **Edge types:** `prerequisite` (concept→concept), `relates_to` (concept↔concept;
  this is the cross-document "same idea as that other paper" link), `part_of`
  (concept hierarchy).

**Schema sketch** (Postgres; all tables learner-scoped + RLS by owner):

```sql
engram_nodes (
  id, learner_id, type,            -- 'concept' | 'preference' | 'goal'
  label, summary,                  -- summary feeds display + embedding
  mastery      real,               -- 0..1, EWMA over evidence (BKT-swappable)
  confidence   real,               -- 0..1, how sure the memory is (self-audit signal)
  salience     real,               -- current activation; decays; bumped on touch
  embedding    vector,             -- pgvector, for relevance retrieval
  source_refs  jsonb,              -- which docs/sessions contributed (opaque to core)
  created_at, last_seen_at
)

engram_edges (
  id, learner_id, source_id, target_id,
  type,                            -- 'prerequisite' | 'relates_to' | 'part_of'
  weight real,
  created_at
)

engram_evidence (                  -- scored episodic items fused onto a node
  id, node_id, kind,               -- explained|asked_about|quiz_correct|quiz_wrong|
                                   --   note|struggle|demonstrated
  content, source_ref, embedding,
  importance real,                 -- set at write (extractor heuristic/LLM)
  created_at
)

engram_events (                    -- append-only raw input + audit trail + Keeper queue
  id, learner_id, type, text, refs jsonb, signals jsonb, ts,
  consolidated_at timestamptz      -- watermark; NULL = not yet processed
)

engram_audit (                     -- every memory-agent operation (observability)
  id, learner_id, op,              -- extract|link|merge|resolve_contradiction|decay|prune|recall
  input_refs jsonb, output_refs jsonb,
  rationale text,                  -- one-line reason from the reflector
  model text, tokens int, cost numeric, ts
)

engram_mastery_history (           -- cheap trajectories for charts
  id, node_id, mastery real, confidence real, ts
)
```

**The generic input shape (the agnostic seam):**
```
LearningEvent {
  learner_id,
  type,        -- 'utterance' | 'tutor_explanation' | 'quiz_result' | 'note' | 'view' | 'highlight' | ...
  text,        -- the content
  refs,        -- { doc_id?, page?, ... } opaque provenance the host understands
  signals,     -- { correct?, confusion?, difficulty?, mastery?, fsrs_due?, ... } OPEN escape hatch
  ts
}
```
The host emits these; the core never knows what a "PDF" is. `signals` is where a
richer host hands in BKT/FSRS so the core can be signal-greedy.

**v1 estimator note:** `mastery` is an **EWMA** (`mastery = α·observation +
(1−α)·mastery_old`, α≈0.3): recent evidence weighted more, old evidence fades.
Cheaper than BKT; swappable behind the same attribute later.

### 4.2 Observability & audit trail (and teacher-dashboard readiness)

Three append-only streams, one purpose each:

| Stream | Direction | Purpose |
|---|---|---|
| `engram_events` | in | raw learning events — the analytics source of truth |
| `engram_audit` | out | every memory-agent operation + rationale — observability + provenance |
| `engram_mastery_history` | snapshot | per-node `(mastery, confidence, ts)` on each consolidation — cheap trajectories |

- Every Keeper op and every Recall writes an `engram_audit` row. This powers
  "why did the tutor say that" provenance, and is what you screen-record to show
  the agent thinking.
- **Teacher-dashboard readiness (structure now, UI later — not this hackathon's
  focus).** Because all three streams are append-only, typed, timestamped, and
  learner-scoped, a downstream *insights read-model* can derive (without touching
  the core): mastery trajectory per concept; struggle hotspots + misconception
  emergence→resolution; "how they learn" (preference nodes + which contexts
  preceded mastery gains); engagement/time-on-concept.
- **Contract that keeps the core agnostic:** the core only *produces this
  substrate*. A dashboard is a separate consumer (a Marfini adapter reading these
  tables). Ship at most a thin read-only `insights` query module (a few functions
  like `mastery_timeline(learner, concept)`) as **optional/stretch**; the
  *guarantee* is the schema.

### 4.3 The two agents

**Tutor agent (fast, hot path, cheap).** Per turn:
1. Take learner utterance + current context (e.g. the slide image in voice).
2. Call **Recall** (no LLM — see §4.4) → token-budgeted subgraph block.
3. Compose prompt: cached stable system prefix + the subgraph block + recent
   turns. One streamed LLM call (vision-capable for slides).
4. **Emit `LearningEvent`s** as a side effect (asked_about, tutor_explanation,
   detected struggle/demonstration). It does **not** write the graph directly.

**Memory Keeper agent (slow, offline; all reasoning cost lives here).** Consumes
un-consolidated `engram_events` for a learner and runs:
1. **Extract** — pull candidate concepts/preferences/goals + evidence from the new
   events. One batched structured-output call over the whole sitting.
2. **Link** — vector-match extracted concepts to existing nodes; create
   `prerequisite`/`relates_to`/`part_of` edges. (Vector ops, no LLM in the common
   case — this is where cross-document links form.)
3. **Merge** — dedupe near-identical nodes (embedding similarity; a confirm LLM
   call only when ambiguous).
4. **Resolve contradictions** — when new evidence conflicts with a node's state
   ("thought they didn't know X; just demonstrated it"), update mastery/confidence
   and write a `resolve_contradiction` audit row.
5. **Decay + prune** — age salience on untouched nodes; drop evidence/nodes below
   threshold. This is *timely forgetting*.
6. **Snapshot** — write `mastery_history` rows; set `consolidated_at` watermark on
   processed events.

**Triggers (when the Keeper "sleeps"):** consolidation is one idempotent core
entry point, `keeper.consolidate(learner_id)`, callable from three triggers that
live in the *host/deployment layer*, never the core:
- **Primary — session end:** on voice WebSocket disconnect, fire a background
  task → `consolidate`. Natural "sleep" boundary; batches the whole sitting.
- **Backstop — cron sweep:** a scheduled job finds learners with events that are
  *unconsolidated AND quiet for N minutes* and calls `consolidate`. This folds in
  the "debounce" idea (it's just the sweep's predicate) and covers crashes/
  abandoned sessions/very long sittings. Precedent: Starnotes' startup
  orphan-session reaper.
- **On-demand — "consolidate now":** a button, for the demo (watch the graph
  reorganize + audit log fill) and power users.

**Idempotency & scope:** `consolidate` only processes events with
`consolidated_at IS NULL`, so racing triggers are safe (add a per-learner
advisory lock if strict). **Consolidate per-learner, not per-session** — the
graph is cross-document; `consolidate(learner_id)` drains *all* the learner's
pending events so cross-doc `relates_to` edges form naturally.

### 4.4 Recall — token-budgeted subgraph (no LLM on the hot path)

Given `(learner_id, query_topic, token_budget)`:
1. Embed the query topic (cache aggressively).
2. pgvector search over `engram_nodes.embedding` → seed concept nodes by relevance.
3. Bounded 1–2 hop expansion along `prerequisite`/`relates_to` → connected +
   cross-document context.
4. Score each candidate node:
   `score = w_r·recency(salience) + w_i·importance + w_v·relevance(vector_sim)`
   (Generative-Agents-style weighting; tune weights).
5. Greedily fill the **token budget**: each node → one compact line + its top 1–2
   evidence snippets; stop at budget.
6. Return **both**: a `text_block` (for the tutor prompt) and the structured
   `subgraph` (for viz + provenance).

Hot-path cost: one (often cached) embedding + a vector query + a bounded
traversal. Target **<50ms server-side**, and **prefetched on PTT-start** so it's
~0 perceived latency. No LLM call.

### 4.5 Forgetting & consolidation details

- **Decay:** on each consolidation, `salience *= decay_factor^(Δt)` for untouched
  nodes; touched nodes get a salience bump. Evidence importance similarly ages.
- **Prune:** nodes/evidence below a salience/importance floor are deleted (or
  soft-deleted with a `forgotten_at` if we want the viz to fade them out before
  removal — recommended for the demo, since *visible forgetting* is a wow beat).
- **Confidence** rises with corroborating evidence, drops on contradiction; low
  confidence makes a node a candidate for re-verification by the tutor.

### 4.6 Ports & adapters (the agnostic surface — small on purpose)

```
HostPort      core.ingest(events)                  # host → core: LearningEvent[]
              core.recall(learner, query, budget)  # → { text_block, subgraph }
              core.consolidate(learner)            # idempotent Keeper entry
              core.graph(learner, focus?)          # → render-ready { nodes, edges }

StoragePort   nodes/edges/evidence/events/audit/mastery_history CRUD + vector_search
              concrete impl: Postgres + pgvector (Supabase). ONE real impl; thin port.

LLMPort       complete(role, messages, schema?) -> { text|json, usage }
              embed(texts) -> vectors
              role ∈ { tutor, extractor, reflector, embedder }
```
- App-specific glue lives in **adapters**, never the core. The Starnotes adapter
  maps its voice WS + notes + quizzes into `LearningEvent`s. A future Marfini
  adapter maps its signals (incl. BKT/FSRS) into `signals`. Adapters are
  replaceable; the core is the asset.
- Coupling is fine *inside adapters and the demo voice UI* — those are meant to
  be throwaway glue. Keep the core pure.

### 4.7 Model tiering / LLM router

A tiny config maps each role → `(provider, model, params)`. Tiering is the #1
cost lever.

| Role | Volume | Needs | Hackathon (Qwen via DashScope) | Cheaper-later swap |
|---|---|---|---|---|
| `tutor` | high (per turn) | fast, vision (reads slides), voice-style | Qwen3-VL (Starnotes already uses it) | distilled / smaller VL |
| `extractor` | medium (per consolidation) | structured output, cheap | qwen-turbo-class | small open model |
| `reflector` | low (merges, contradictions) | judgment/reasoning | qwen-max / Qwen3 reasoning tier | the only role needing a big model |
| `embedder` | high | cheap embeddings | DashScope `text-embedding-v*` | self-hosted |

> **Confirm at build time:** exact Qwen model slugs, context limits, vision
> support, and pricing against the live Alibaba Cloud Model Studio (DashScope)
> catalog. Do not hard-code prices that drift. DashScope offers an
> OpenAI-compatible endpoint (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
> or the region-appropriate host) — the adapter is essentially the OpenAI client
> pointed there.

Swapping any role later = a config edit, not a refactor.

### 4.8 React Flow visualization contract

`core.graph(learner, focus?)` returns render-ready data:
```
nodes: [{ id, type, label, mastery, confidence, salience, last_seen_at, evidence_count }]
edges: [{ id, source, target, type, weight }]   # prerequisite = solid, relates_to = dashed
```
Visual encoding doubles as the demo:
- node **size/color** = mastery; **opacity** = salience (decaying/forgotten
  memories visibly fade); edge style = type (mirrors Marfini's concept-map
  convention so the component ports over).
- click a node → its evidence list + audit provenance.
- `graph()` returns a **bounded view** (focus + N hops, or top-K by salience) so
  large graphs don't dump thousands of nodes.

---

## 5. Alibaba Cloud deployment fit (the gating requirement)

- **Backend on Alibaba compute:** run the FastAPI app (REST + voice WebSocket) on
  a **container host** — Alibaba **ECS** or **Serverless App Engine (SAE)** —
  because the voice WebSocket wants a long-lived connection (Function Compute WS
  is fiddly). A Dockerfile exists in Starnotes to adapt.
- **Keeper cron** → **Alibaba Function Compute scheduled trigger** hitting a
  `/consolidate-sweep` endpoint. This gives a clean multi-service story.
- **Inference** → **Alibaba Cloud Model Studio (DashScope)** for all Qwen calls.
- **The required "code file demonstrating Alibaba Cloud APIs"** = the **DashScope
  `LLMPort` adapter**. Point the submission's required link directly at it.
- **Keep Supabase** for Postgres+pgvector+auth+storage. The rule is "backend on
  Alibaba + uses Alibaba services," satisfied by SAE/ECS + Function Compute +
  DashScope. *Optional deeper-Alibaba lever (post-hackathon or if judges reward
  it):* move the DB to **Alibaba RDS for PostgreSQL / PolarDB** (both support
  pgvector).
- **Do Phase 0 first** (deploy a hello-world that calls DashScope on Alibaba)
  before building features — it's the highest-uncertainty, disqualify-if-missing
  requirement.

---

## 6. Cost & performance budget

**Hot path (per voice turn):**
- Recall: 1 (often cached) embedding + vector query + bounded traversal →
  **<50ms server-side, prefetched → ~0 perceived**.
- Tutor: 1 streamed vision call with a **cached system prefix** (~80% prefix
  savings). Vision (slide image) is the dominant token cost, unchanged from today.
- **Zero Keeper work on the hot path.** Memory adds negligible latency.

**Consolidation (per sleep, amortized over a whole sitting):**
- Batched to **~2–4 LLM calls regardless of turn count**: extract once over the
  batch; linking is vector-only/no-LLM; merge/contradiction calls fire *only* on
  ambiguous cases; reflect once.
- Target: a few cents per sitting (Starnotes' lecture gen ≈ $0.08 for scale
  reference); tunable down via tiering.

**Cost/perf levers, consolidated:** model tiering · prompt caching · batched
extraction · vector-only linking · incremental consolidation (watermark) ·
embedding cache · bounded recall budget · bounded graph view · pruning keeps the
graph small (stores concepts, not transcripts).

---

## 7. Eval — the "it gets better" proof

Most Track 1 entries won't measure this; a lightweight real eval is the
engineering-excellence edge and the video's money-shot.

- **Design:** an **ablation** — run identical scripted learner arcs twice:
  *memory ON* vs *naive last-N-dump baseline*. Measure the gap. Run against the
  **core directly** with a fake host adapter feeding scripted events (the
  agnostic payoff — no full app needed).
- **StudentSimulator:** an LLM-driven learner with a persona + known state, driving
  multi-session conversations against the real tutor+memory. (Lift Marfini's
  `NEW_FEATURES.md` §1 design.)
- **Scenario YAMLs:** persona + scripted multi-session arc + expected behaviors
  (e.g. "session 3: must NOT re-explain derivatives [mastered s1], SHOULD recall
  the pinch-off confusion from s1").
- **Metrics:** deterministic counters (re-explanation rate of mastered concepts ↓,
  prior-session recall-hit rate ↑, preference-honored rate ↑) + a light LLM judge
  for "did it adapt appropriately."
- **Money-shot for the video:** "With memory, the tutor re-explained mastered
  material X% less and recalled prior-session context N/M times vs. the baseline."

---

## 8. Phasing plan (≈1 month; always a shippable cut)

| Phase | Deliverable | Why this order |
|---|---|---|
| **0 — Foundations** | New repo + LICENSE; core skeleton with the 3 ports; pgvector schema (nodes/edges/evidence/events/audit/mastery_history); **DashScope `LLMPort` adapter; hello-world FastAPI deployed on Alibaba compute calling DashScope** | De-risk the gating Alibaba requirement first |
| **1 — Ingest + Recall** | `LearningEvent` ingest; budgeted Recall (§4.4); minimal tutor turn (seed the graph by hand to test recall before the Keeper exists) | Prove the read path end-to-end |
| **2 — Memory Keeper** | extract→link→merge→resolve→decay→prune→snapshot; `consolidate()` + session-end trigger + "consolidate now" | The core IP |
| **3 — Voice host adapter** | Port the Starnotes PTT voice WS in as the host adapter; emit events; consume Recall; consolidate on session end | The live demo surface |
| **4 — Graph viz + provenance** | React Flow graph (§4.8); node→evidence+audit detail; "consolidate now → watch it reorganize + fade forgotten nodes" | The wow + the demo |
| **5 — Eval + cron + polish** | StudentSimulator + scenarios + the metric (§7); Function Compute cron sweep; multi-provider config proof; submission artifacts (3-min video, architecture diagram, README, LICENSE, Alibaba recording) | Credibility + robustness |

**Hard-MVP if time compresses:** Phases 0–4 = a working, demoable submission.
Phase 5 is the credibility/robustness layer (and several mandatory artifacts —
don't skip the video/diagram/license).

---

## 9. Open decisions / confirm-at-build-time

1. **Qwen model slugs, vision support, context limits, prices** — confirm against
   the live DashScope catalog (§4.7). Pick per-role models then.
2. **Alibaba compute target** — ECS vs SAE for the WS service; confirm WebSocket
   support + cold-start behavior on the chosen option.
3. **STT/TTS providers** — Starnotes uses Groq Whisper + OpenAI TTS. Decide
   whether to keep them (fine — they're behind seams and not the judged part) or
   move to Alibaba equivalents for a stronger "all-Alibaba" story. Not required.
4. **Embedding model** — DashScope `text-embedding-v*` vs keeping an existing
   provider behind the port. Prefer DashScope for the Alibaba story.
5. **Recall scoring weights** (`w_r`, `w_i`, `w_v`) and **decay factor** — tune
   empirically with the eval harness.
6. **Soft-delete vs hard-delete** on prune — recommend soft-delete with
   `forgotten_at` so the viz can fade nodes before removal (demo value).
7. **`insights` read module** — build the thin read-only stub (optional/stretch)
   or ship schema-only? Default: schema-only unless time allows.

---

## 10. Submission artifacts checklist (don't lose mandatory points)

- [ ] Public repo + **LICENSE** at root (MIT/Apache-2.0), visible in About.
- [ ] Backend **running on Alibaba Cloud** + a short **recording** proving it.
- [ ] **Link to the DashScope adapter file** as the "uses Alibaba Cloud APIs" proof.
- [ ] **Architecture diagram** (Qwen Cloud ↔ backend ↔ DB ↔ frontend).
- [ ] **~3-min demo video** (public, YouTube/Vimeo/FB) — lead with the memory
      wow: graph growing, "it remembered," the ablation number.
- [ ] **Text description** of features.
- [ ] **Track 1** identified.
- [ ] *Optional:* build-journey blog post (Blog Prize eligibility).
```
