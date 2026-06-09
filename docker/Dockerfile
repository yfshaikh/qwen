# Engram backend (FastAPI + asyncpg + pgvector + OpenRouter).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg / numpy / general health checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -U pip && pip install -e .

# Schema is applied by the db container on first init; bundled here too so it
# can be applied manually against a managed DB (e.g. Alibaba RDS) if needed.
COPY migrations ./migrations

EXPOSE 8000

# Single worker — the POC hosts one instance; scale later behind a load balancer.
CMD ["uvicorn", "engram.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
