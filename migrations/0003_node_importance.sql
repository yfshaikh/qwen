-- 0003: node-level importance (memory-quality-fixes spec §4 / known issue #3).
-- Nullable: NULL means "extractor never scored it"; recall treats NULL as a
-- neutral 0.3 prior so pre-migration graphs don't crater.
ALTER TABLE engram_nodes ADD COLUMN IF NOT EXISTS importance real;
