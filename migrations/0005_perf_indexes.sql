-- 0005: covering indexes for recall expansion, graph build, keeper linking,
-- and events queries (architecture-optimization remediation, task B6 /
-- WS-6a/6b). Additive only — no behavior change, purely removes seq scans.
--
-- engram_edges_learner_target: 0001 already indexes (learner_id, source_id)
-- for the edge lookup's `source_id = ANY(...)` half; this covers the
-- `target_id = ANY(...)` half of the same OR (get_edges, used by
-- core/graph.py build, core/keeper.py linking, core/recall.py expansion).
--
-- engram_events_learner_ts: covers get_events' `WHERE learner_id = $1
-- ORDER BY ts DESC` (core/engram.py get_events).
--
-- engram_events_pending_ts: 0001's engram_events_pending index is
-- (learner_id) WHERE consolidated_at IS NULL only; get_pending_events also
-- orders by ts (core/keeper.py linking, core/recall.py buffer fetch), so
-- this adds ts to the partial index rather than duplicating it.

CREATE INDEX IF NOT EXISTS engram_edges_learner_target
  ON engram_edges (learner_id, target_id);
CREATE INDEX IF NOT EXISTS engram_events_learner_ts
  ON engram_events (learner_id, ts);
CREATE INDEX IF NOT EXISTS engram_events_pending_ts
  ON engram_events (learner_id, ts) WHERE consolidated_at IS NULL;
