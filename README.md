# Engram

App-agnostic memory core for AI tutors: turns a stream of generic learning
events into a living knowledge graph of a learner, maintained by an offline
"Memory Keeper" agent and read by a fast, token-budgeted Recall.

See `docs/DESIGN.md` for the full architecture and
`docs/superpowers/specs/2026-06-13-engram-mvp-openrouter-design.md` for the MVP
build (OpenRouter + OpenAI embeddings + local Docker Postgres).

## Dev quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then fill in real keys
docker compose up -d          # local pgvector on :5432
pytest                        # run the suite
```

## Try the tutor (live)

After `cp .env.example .env` and adding your real OpenRouter + OpenAI keys
(Docker Postgres up):

```bash
.venv/bin/python scripts/demo_chat.py
```

Boots the HTTP service and streams a `/chat` turn end-to-end — printing the
recalled memory, the live reply, and the raw events saved — then consolidates
and prints the audit log, so you can watch the Keeper turn the conversation into
graph memory.

## License

MIT — see `LICENSE`.
