-- Superseded reconciliation items (specs/cfo-reconciliation-workflow.md section 5): the bridge closes
-- an untouched item once a newer run of its source has replaced it, instead of leaving a CFO task
-- whose record-level detail is gone. Widens pipeline_reconciliation's status with SUPERSEDED. Safe to
-- run more than once. db/schema.sql already contains this for fresh installs. Needs migration 009
-- first. Apply with:
--   python db/apply_migration.py db/migrations/020_reconciliation_superseded.sql
BEGIN;

ALTER TABLE pipeline_reconciliation DROP CONSTRAINT IF EXISTS pipeline_reconciliation_status_check;
ALTER TABLE pipeline_reconciliation ADD CONSTRAINT pipeline_reconciliation_status_check
    CHECK (status IN ('OPEN', 'MATCHED', 'WITH_CFO', 'ASSIGNED', 'SUBMITTED', 'APPROVED', 'SUPERSEDED'));

COMMIT;
