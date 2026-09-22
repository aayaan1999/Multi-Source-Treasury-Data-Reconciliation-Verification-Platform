-- Widens camunda_process_tracking.record_type to allow 'breach' (specs/screen-06-report-workflow.md
-- section 2.4: an auto-created breach becomes "another flagCategory-routed Camunda process
-- instance, not a separate alert system" - it reuses the existing 'compliance' candidate group,
-- so no BPMN change is needed, just this record_type). Robust to whatever Postgres auto-named the
-- inline CHECK constraint, rather than assuming camunda_process_tracking_record_type_check. Safe
-- to run more than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/005_breach_record_type.sql
BEGIN;

DO $$
DECLARE
    con text;
BEGIN
    SELECT conname INTO con FROM pg_constraint
    WHERE conrelid = 'camunda_process_tracking'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%record_type%';
    IF con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE camunda_process_tracking DROP CONSTRAINT %I', con);
    END IF;
END $$;

ALTER TABLE camunda_process_tracking ADD CONSTRAINT camunda_process_tracking_record_type_check
    CHECK (record_type IN ('data_quality', 'fraud', 'breach'));

COMMIT;
