-- Adds camunda_process_tracking (specs/camunda-bpmn-process-design.md section 4) to a database
-- that was created from an earlier db/schema.sql. Safe to run more than once. db/schema.sql
-- already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/003_camunda_process_tracking.sql
BEGIN;

-- Lets the polling bridge worker (camunda/bridge/poll_worker.py) tell which
-- data_quality_exceptions / flagged_transactions rows already have a running or completed
-- transaction-review process instance, without writing a process-tracking column onto tables
-- that Databricks' import job owns and overwrites (data_quality_exceptions) or that already carry
-- a different mutable field (flagged_transactions.status, the review *outcome*, not "was a
-- process started").
CREATE TABLE IF NOT EXISTS camunda_process_tracking (
    record_type          text NOT NULL CHECK (record_type IN ('data_quality', 'fraud')),
    source_table          text NOT NULL,
    record_key            text NOT NULL,
    flag_label            text NOT NULL,
    process_instance_key  bigint NOT NULL,
    started_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (record_type, source_table, record_key, flag_label)
);

COMMIT;
