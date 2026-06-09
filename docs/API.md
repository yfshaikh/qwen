# Engram HTTP API (Phase 0–4)

The FastAPI app (`engram.app.main:app`) exposes the core over HTTP. The React
frontend and any host adapter consume exactly this contract. All bodies are JSON.

Composition: the app wires `EngramService(storage, llm)` once at startup
(`engram.app.deps`). `storage` is Postgres (default) or in-memory
(`ENGRAM_STORAGE_BACKEND=memory`); `llm` is OpenRouter chat + local embedder.

## Shapes

**Node dict** (in `/graph` and recall subgraphs):
```json
{"id": "uuid", "type": "concept|preference|goal", "label": "str",
 "mastery": 0.0, "confidence": 0.0, "salience": 0.0,
 "last_seen_at": "iso8601", "evidence_count": 0, "forgotten_at": null}
```
**Edge dict**:
```json
{"id": "uuid", "source": "uuid", "target": "uuid",
 "type": "prerequisite|relates_to|part_of", "weight": 1.0}
```

## Endpoints

### `GET /health`
Liveness + DB reachability. `200 {"status":"ok","db":"ok"}` or `503` with
`{"detail":{"status":"degraded","db":"down"}}`.

### `POST /llm-ping`
Body `{"prompt": "str"}` → `{"completion": str|null, "embedding_dim": int,
"usage": {...}, "model": str|null}`. Exercises `LLMPort.complete` + `.embed`.
(Needs an OpenRouter key for a real completion; embeddings are local.)

### `POST /ingest`
Body `{"learner_id": "str", "events": [{"type": "str", "text": "str?",
"refs": {}, "signals": {}}]}` → `{"ids": ["uuid", ...]}`. Append-only.

### `POST /recall`
Body `{"learner_id": "str", "query": "str", "budget": 600}` →
`{"text_block": "str", "subgraph": {"nodes": [Node...], "edges": [Edge...]}}`.
No LLM reasoning on this path (one embed call only).

### `POST /consolidate`
Body `{"learner_id": "str"}` → `{"stats": {"events_processed": int,
"nodes_created": int, "nodes_updated": int, "edges_created": int,
"merged": int, "pruned": int}}`. Runs the Memory Keeper. (Needs an LLM key for
extraction.) This is the "consolidate now" button.

### `POST /consolidate-sweep`
Body `{"quiet_seconds": 120}` → `{"learners": ["..."], "stats": {learner: {...}}}`.
The cron backstop: consolidate every learner with pending, quiet events.

### `GET /graph?learner_id=...&focus=...&hops=1`
→ `{"nodes": [Node...], "edges": [Edge...]}`. Bounded render-ready view for
React Flow. `focus` optional (center on a concept); `hops` default 1.

### `GET /audit?learner_id=...&limit=100`
→ `{"entries": [{"op": "str", "rationale": "str?", "model": "str?",
"tokens": int?, "ts": "iso8601", "input_refs": {}, "output_refs": {}}]}`.
Provenance / "watch the agent think".

### `POST /tutor/turn`
Body `{"learner_id": "str", "message": "str", "session_id": "str?",
"doc_ref": {}}` → `{"reply": "str", "recall": {"text_block": "str",
"subgraph": {...}}, "events_emitted": int}`. One tutor turn: recall → compose
prompt (cached system prefix + recall block) → `LLMPort.complete(role="tutor")`
→ emit `LearningEvent`s (asked_about, tutor_explanation) as a side effect.
Consolidation happens out-of-band (button or sweep), not per turn.
