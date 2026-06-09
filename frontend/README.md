# Engram frontend

Single-page React app that makes a learner's memory graph visible and
demonstrates the memory loop (ingest → consolidate → recall → tutor turn).
Built with Vite + TypeScript + [React Flow](https://reactflow.dev) (`@xyflow/react`).

## Develop

Requires Node 22. The backend API is expected at `http://localhost:8000`
(see `docker-compose.yml` at the repo root / `engram.app.main:app`).

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server proxies all API paths (`/graph`, `/evidence`, `/ingest`,
`/consolidate`, `/recall`, `/audit`, `/tutor`, `/health`, `/llm-ping`) to the
backend, so no CORS configuration is needed. To point the proxy elsewhere:

```bash
ENGRAM_API_TARGET=http://other-host:8000 npm run dev
```

## Production builds and `VITE_API_BASE`

In production the API base URL is baked into the bundle at build time via the
`VITE_API_BASE` env var:

```bash
VITE_API_BASE=https://api.example.com npm run build   # output in dist/
```

If `VITE_API_BASE` is unset/empty, the app uses relative paths — correct when
the SPA is served behind the same origin or reverse proxy as the API.

## Docker

Multi-stage build (node:22-alpine → nginx:alpine, SPA fallback on port 80):

```bash
cd frontend
docker build -t engram-frontend .
# or bake an API base URL:
docker build --build-arg VITE_API_BASE=https://api.example.com -t engram-frontend .

docker run --rm -p 8080:80 engram-frontend   # http://localhost:8080
```

## What's in the UI

- **Learner selector** — `learner_id` input (default `alice`) + Load.
- **Memory graph** — React Flow canvas of `GET /graph`. Node size & color encode
  mastery (red → amber → green), opacity encodes salience (fading = forgetting),
  with a type badge (concept / preference / goal). Edge styles: `prerequisite`
  solid + arrow, `relates_to` dashed, `part_of` thin. Layout is a deterministic
  client-side force layout seeded from node-id hashes (stable across reloads).
- **Node detail panel** (click a node) — mastery/confidence/salience bars,
  evidence count, last-seen, the node's evidence list (`GET /evidence`), and
  recent provenance from `GET /audit`.
- **Tutor chat** — `POST /tutor/turn`; shows the reply plus "what the tutor
  remembered" (`recall.text_block`), then refreshes graph + audit.
- **Consolidate now** — `POST /consolidate`; shows the returned stats briefly
  and refreshes so you can watch the graph reorganize.
- **Ingest helper** — collapsible form posting one raw `{type, text}` event to
  `POST /ingest` for seeding demos.

Tutor replies and consolidation need an LLM key on the backend; without one
the app stays usable (graph / ingest / audit / evidence) and API failures show
as dismissible error toasts.

The API contract lives in `../docs/API.md`.
