# Engram backend — FastAPI service (uvicorn on :8050).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1. Dependency layer. Copy only the project metadata, then install. A stub
#    package lets the editable install resolve and pull every dependency; the
#    real source is copied in the next layer and picked up through the editable
#    link. Result: `pip install` is cached until pyproject.toml changes, so
#    source edits don't re-resolve the dependency tree.
COPY pyproject.toml README.md ./
RUN mkdir -p src/engram \
 && : > src/engram/__init__.py \
 && pip install -e .

# 2. Source layer. The real package overwrites the stub; migrations ship along
#    so the image is self-contained (schema.sql is handy for manual DB setup).
COPY src/ ./src/
COPY migrations/ ./migrations/

EXPOSE 8050

CMD ["uvicorn", "engram.app.main:app", "--host", "0.0.0.0", "--port", "8050"]
