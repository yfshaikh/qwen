-- 0004: enforce "one edge per undirected node pair" at the source (review
-- guardrail, 2026-07-11). The Keeper's link step and merge_nodes maintain this
-- invariant in code; the index makes out-of-band writers (fixture loads, seeds,
-- future adapters) fail loudly instead of silently duplicating — known-issue
-- #5's root cause.
--
-- One-time cleanup first: self-loops, then the weaker edge of every duplicate
-- pair. Precedence must stay in sync with engram.core.edges.EDGE_RANK
-- (prerequisite > part_of > relates_to), then weight, then id.

DELETE FROM engram_edges WHERE source_id = target_id;

DELETE FROM engram_edges a USING engram_edges b
WHERE a.learner_id = b.learner_id AND a.id <> b.id
  AND ((a.source_id = b.source_id AND a.target_id = b.target_id)
    OR (a.source_id = b.target_id AND a.target_id = b.source_id))
  AND (CASE a.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
       a.weight, a.id)
    < (CASE b.type WHEN 'prerequisite' THEN 2 WHEN 'part_of' THEN 1 ELSE 0 END,
       b.weight, b.id);

CREATE UNIQUE INDEX IF NOT EXISTS engram_edges_undirected_pair
  ON engram_edges (learner_id, LEAST(source_id, target_id), GREATEST(source_id, target_id));
