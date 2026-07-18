-- migrations/0002_voice_sessions.sql
-- Voice-tutor sessions + turns. Host-layer tables (not part of the memory graph);
-- power the console's session sidebar + per-session transcripts.

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
