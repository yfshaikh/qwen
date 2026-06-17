-- Phase 0 schema. Full DDL from the spec. Only health()'s existence check uses
-- these tables in Phase 0; Phases 1–2 add the real reads/writes.
--
-- Embedding dim: vector(1024) is the single source of truth for the embedding
-- dimension and MUST match ENGRAM_EMBEDDING_DIM in .env. Changing the dimension
-- means editing both. (Templated DDL is deliberately out of scope for Phase 0.)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS engram_nodes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id    text NOT NULL,
  type          text NOT NULL CHECK (type IN ('concept','preference','goal')),
  label         text NOT NULL,
  summary       text,
  mastery       real,
  confidence    real,
  salience      real,
  embedding     vector(1024),
  source_refs   jsonb NOT NULL DEFAULT '[]'::jsonb,
  forgotten_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engram_nodes_embedding_hnsw
  ON engram_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS engram_nodes_learner_type
  ON engram_nodes (learner_id, type);

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
