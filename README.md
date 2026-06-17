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

## License

MIT — see `LICENSE`.
