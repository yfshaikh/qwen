# Engram Frontend

A single-page React app that makes a learner's **memory graph** visible and
demonstrates the Engram memory loop (ingest → consolidate → recall → tutor turn).
This is a **proof of concept**: functional and clear, not heavily polished.

Stack: **React + TypeScript + Vite + React Flow** (`@xyflow/react`).

## What it shows

- **Memory graph** (React Flow): node **size + color** encode `mastery`
  (red → amber → green), **opacity** encodes `salience` (decayed/forgotten
  memories fade), a corner **badge** encodes node type (concept / preference /
  goal). Edges follow a concept-map convention: `prerequisite` = solid + arrow,
  `relates_to` = dashed, `part_of` = solid thin. Layout is a deterministic
  client-side force layout (the API returns no positions).
- **Detail panel**: click a node to see `mastery`, `confidence`, `salience`,
  `evidence_count`, timestamps, and the recent **audit / provenance** feed.
- **Chat panel**: send a message to `POST /tutor/turn`, see the tutor `reply`
  plus the **recall block** ("what the tutor remembered"); the graph refreshes
  after each turn.
- **Consolidate now**: runs `POST /consolidate`, shows the returned stats, and
  refreshes the graph + audit — the "watch the graph reorganize" demo beat.
- **Ingest helper**: a small form to `POST /ingest` a raw event to seed a demo
  without curl.

## Run (dev)

```bash
npm install
npm run dev
```

Open http://localhost:5173 . Enter a `learner_id` (default `alice`) and click
**Load**.

### Talking to the backend

Two supported approaches (pick one):

1. **Dev proxy (default).** Leave `VITE_API_BASE` unset. The app calls
   same-origin paths (`/graph`, `/ingest`, …) and the Vite dev server proxies
   them to `http://localhost:8000` (see `vite.config.ts`). No CORS setup needed.
   To point the proxy elsewhere, set `VITE_API_BASE` before `npm run dev`
   (it is also used as the proxy target):

   ```bash
   VITE_API_BASE=http://localhost:9000 npm run dev
   ```

2. **Direct base URL.** Set `VITE_API_BASE` to the backend origin and the app
   calls it directly (the backend must allow CORS):

   ```bash
   VITE_API_BASE=http://localhost:8000 npm run dev
   ```

> The Engram backend defaults to port **8000**. Graph / ingest / consolidate /
> recall work without any LLM key (local embeddings). The tutor **reply** text
> needs a backend OpenRouter key; without it the turn still succeeds but the
> reply may be empty — the UI handles that gracefully.

## Build (production)

```bash
npm run build      # tsc -b && vite build  -> dist/
npm run preview    # serve dist/ locally
```

`VITE_API_BASE` is read at **build time**, so set it before building for static
hosting:

```bash
VITE_API_BASE=https://api.example.com npm run build
```

## Docker

Multi-stage build (`node` build → `nginx:alpine` serving static files on port 80,
with SPA fallback to `index.html`):

```bash
# build (optionally bake in the API base)
docker build -t engram-frontend .
# or:
docker build --build-arg VITE_API_BASE=https://api.example.com -t engram-frontend .

# run
docker run --rm -p 8080:80 engram-frontend
# open http://localhost:8080
```

If you leave `VITE_API_BASE` empty in the image, front the app and the API
behind one reverse proxy so same-origin `/graph` etc. resolve.

## API

The full contract is in [`../docs/API.md`](../docs/API.md). Types live in
`src/lib/types.ts`; the fetch wrapper is `src/lib/api.ts`. Non-200 responses and
network errors are surfaced as a dismissible toast instead of crashing.
