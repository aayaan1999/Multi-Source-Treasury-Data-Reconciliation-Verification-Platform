-- CFO reconciliation workflow (specs/cfo-reconciliation-workflow.md, FLOW-5): widens
-- pipeline_reconciliation's status for the workflow and records who it's assigned to / approved
-- by; adds reconciliation_corrections (values proposed for the rejected records behind an item);
-- adds data_quality_exceptions.record_data (the rejected row's own values, from Notebook 2); and
-- lets camunda_process_tracking record reconciliation processes. Robust to whatever Postgres
-- auto-named the inline CHECK constraints. Safe to run more than once. db/schema.sql already
-- contains this for fresh installs. Needs migration 008 first. Apply with:
--   python db/apply_migration.py db/migrations/009_cfo_reconciliation_workflow.sql
BEGIN;

-- Drop the named CHECK constraint on a table's column, whatever it was called.
DO $$
DECLARE
    con text;
BEGIN
    SELECT conname INTO con FROM pg_constraint
    WHERE conrelid = 'pipeline_reconciliation'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%';
    IF con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE pipeline_reconciliation DROP CONSTRAINT %I', con);
    END IF;
    SELECT conname INTO con FROM pg_constraint
    WHERE conrelid = 'camunda_process_tracking'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%record_type%';
    IF con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE camunda_process_tracking DROP CONSTRAINT %I', con);
    END IF;
END $$;

ALTER TABLE pipeline_reconciliation ADD CONSTRAINT pipeline_reconciliation_status_check
    CHECK (status IN ('OPEN', 'MATCHED', 'WITH_CFO', 'ASSIGNED', 'SUBMITTED', 'APPROVED'));
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS assigned_to integer REFERENCES users (user_id);
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS approved_by integer REFERENCES users (user_id);
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS approved_at timestamptz;

ALTER TABLE camunda_process_tracking ADD CONSTRAINT camunda_process_tracking_record_type_check
    CHECK (record_type IN ('data_quality', 'fraud', 'breach', 'reconciliation'));

ALTER TABLE data_quality_exceptions ADD COLUMN IF NOT EXISTS record_data jsonb;

CREATE TABLE IF NOT EXISTS reconciliation_corrections (
    correction_id  bigserial PRIMARY KEY,
    recon_id       bigint NOT NULL REFERENCES pipeline_reconciliation (recon_id),
    source_table   text NOT NULL,
    record_key     text NOT NULL,
    field_name     text NOT NULL,
    old_value      text,
    new_value      text NOT NULL,
    entered_by     integer NOT NULL REFERENCES users (user_id),
    entered_at     timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED', 'APPROVED')),
    approved_by    integer REFERENCES users (user_id),
    approved_at    timestamptz,
    synced_at      timestamptz          -- set when Databricks has applied it (5b)
);

-- One live proposal per record field in an item: a new value replaces the old proposal.
CREATE UNIQUE INDEX IF NOT EXISTS reconciliation_corrections_one_per_field
    ON reconciliation_corrections (recon_id, source_table, record_key, field_name) WHERE status = 'PROPOSED';

COMMIT;
