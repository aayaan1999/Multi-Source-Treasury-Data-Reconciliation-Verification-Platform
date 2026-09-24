-- Adds pipeline_reconciliation.note (specs/pipeline-reconciliation.md section 9, FLOW-1b): set by the
-- completeness check to "No rows delivered" when a source's run is missing an expected country or
-- table. Needs migration 008. Safe to run more than once. db/schema.sql already contains this for
-- fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/011_pipeline_reconciliation_note.sql
BEGIN;

ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS note text;

COMMIT;
