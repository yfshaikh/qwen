-- Consolidated Engram schema — equivalent to applying migrations 0001–0006 in
-- order. FRESH INSTALLS (embedding Engram in your own project) run just this
-- one file:
--
--     psql "$DATABASE_URL" -f migrations/schema.sql
--
-- Everything is idempotent (IF NOT EXISTS), so it is also harmless on a DB
-- that already ran the numbered migrations — this repo's docker-compose
-- auto-applies migrations/ alphabetically, where this file sorts last.
--
-- MAINTENANCE: when adding migration 000N, fold its DDL in here too and add
-- it to the list below (tests/test_schema_consolidated.py enforces this).
-- Covers: 0001_engram_schema.sql, 0002_voice_sessions.sql,
-- 0003_node_importance.sql, 0004_edge_pair_unique.sql,
-- 0005_perf_indexes.sql, 0006_node_external_id.sql
--
-- Embedding dim: vector(1024) MUST match ENGRAM_EMBEDDING_DIM.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

-- ── Memory graph ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS engram_nodes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id    text NOT NULL,
  type          text NOT NULL CHECK (type IN ('concept','preference','goal')),
  label         text NOT NULL,
  summary       text,
  mastery       real,
  confidence    real,
  salience      real,
  -- NULL importance = "extractor never scored it"; recall treats it as a
  -- neutral 0.3 prior (0003)
  importance    real,
  embedding     vector(1024),
  source_refs   jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- the HOST's stable concept key for ontology-seeded nodes (0006);
  -- NULL = dynamically extracted
  external_id   text,
  forgotten_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_nodes_embedding_hnsw
  ON engram_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS engram_nodes_learner_type
  ON engram_nodes (learner_id, type);
-- a learner must never hold two nodes for one curriculum concept (0006)
CREATE UNIQUE INDEX IF NOT EXISTS engram_nodes_learner_external
  ON engram_nodes (learner_id, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS engram_edges (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  source_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  target_id   uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  type        text NOT NULL CHECK (type IN ('prerequisite','relates_to','part_of')),
  weight      real NOT NULL DEFAULT 1.0,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_edges_learner_source
  ON engram_edges (learner_id, source_id);
CREATE INDEX IF NOT EXISTS engram_edges_learner_target
  ON engram_edges (learner_id, target_id);
-- one edge per undirected node pair, enforced at the source (0004)
CREATE UNIQUE INDEX IF NOT EXISTS engram_edges_undirected_pair
  ON engram_edges (learner_id, LEAST(source_id, target_id), GREATEST(source_id, target_id));

CREATE TABLE IF NOT EXISTS engram_evidence (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  content     text,
  source_ref  jsonb,
  embedding   vector(1024),
  importance  real,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_evidence_node ON engram_evidence (node_id);

CREATE TABLE IF NOT EXISTS engram_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id      text NOT NULL,
  type            text NOT NULL,
  text            text,
  refs            jsonb NOT NULL DEFAULT '{}'::jsonb,
  signals         jsonb NOT NULL DEFAULT '{}'::jsonb,
  ts              timestamptz NOT NULL DEFAULT now(),
  consolidated_at timestamptz
);
CREATE INDEX IF NOT EXISTS engram_events_pending
  ON engram_events (learner_id) WHERE consolidated_at IS NULL;
CREATE INDEX IF NOT EXISTS engram_events_learner_ts
  ON engram_events (learner_id, ts);
CREATE INDEX IF NOT EXISTS engram_events_pending_ts
  ON engram_events (learner_id, ts) WHERE consolidated_at IS NULL;

CREATE TABLE IF NOT EXISTS engram_audit (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  op          text NOT NULL,
  input_refs  jsonb,
  output_refs jsonb,
  rationale   text,
  model       text,
  tokens      int,
  cost        numeric,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_audit_learner_ts ON engram_audit (learner_id, ts);

CREATE TABLE IF NOT EXISTS engram_mastery_history (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id     uuid NOT NULL REFERENCES engram_nodes(id) ON DELETE CASCADE,
  mastery     real,
  confidence  real,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_mastery_history_node_ts
  ON engram_mastery_history (node_id, ts);

-- ── Voice-session store (optional host-layer tables, 0002) ──────────────────

CREATE TABLE IF NOT EXISTS engram_voice_sessions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id  text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  ended_at    timestamptz
);
CREATE INDEX IF NOT EXISTS engram_voice_sessions_learner
  ON engram_voice_sessions (learner_id, started_at DESC);

CREATE TABLE IF NOT EXISTS engram_voice_turns (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid NOT NULL REFERENCES engram_voice_sessions(id) ON DELETE CASCADE,
  learner_id  text NOT NULL,
  role        text NOT NULL CHECK (role IN ('user','assistant')),
  text        text NOT NULL,
  ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_voice_turns_session
  ON engram_voice_turns (session_id, ts);
