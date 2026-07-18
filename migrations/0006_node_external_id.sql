-- 0006: host-supplied ontology (spec 2026-07-15-host-supplied-ontology-design).
-- external_id is the HOST's stable concept key (Marfini's concept UUID, the SAT
-- site's label). NULL = the node came from extraction, which is every node
-- predating this migration — so the ontology paths stay dormant on existing
-- graphs with no backfill.
ALTER TABLE engram_nodes ADD COLUMN IF NOT EXISTS external_id text;

-- Partial: many NULLs are legal (every dynamically-extracted node), but a
-- learner must never hold two nodes for one curriculum concept — that is the
-- exact duplication this feature exists to prevent, and the DB is the only
-- place it can be made impossible rather than merely unlikely.
CREATE UNIQUE INDEX IF NOT EXISTS engram_nodes_learner_external
  ON engram_nodes (learner_id, external_id) WHERE external_id IS NOT NULL;
