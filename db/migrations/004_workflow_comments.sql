-- Extends `comments` (specs/screen-06-report-workflow.md section 2.3) so it can hold comments on
-- a data_quality_exceptions/flagged_transactions record, not just a report_instance_id. Those two
-- source tables don't share a single numeric id (specs/camunda-bpmn-process-design.md section 4's
-- comment on data_quality_exceptions.exception_id vs flagged_transactions' composite key), so a
-- comment on an exception is identified the same way camunda_process_tracking and review_outcomes
-- already key these records: (source_table, record_key, flag_label). Safe to run more than once.
-- db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/004_workflow_comments.sql
BEGIN;

ALTER TABLE comments ALTER COLUMN report_instance_id DROP NOT NULL;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS source_table text;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS record_key text;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS flag_label text;

ALTER TABLE comments DROP CONSTRAINT IF EXISTS comments_target_check;
ALTER TABLE comments ADD CONSTRAINT comments_target_check CHECK (
    (report_instance_id IS NOT NULL AND source_table IS NULL AND record_key IS NULL AND flag_label IS NULL)
    OR (report_instance_id IS NULL AND source_table IS NOT NULL AND record_key IS NOT NULL AND flag_label IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS comments_exception_idx ON comments (source_table, record_key, flag_label);

COMMIT;
