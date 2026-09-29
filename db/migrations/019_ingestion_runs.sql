-- One row per source-notebook run (e.g. Salesforce), written by the notebook itself so the Data Ingestion
-- screen's "Recent ingestions" shows loads from connected sources, not only the core banking files
-- (specs/screen-data-ingestion.md, backlog ING-4). Safe to run more than once. db/schema.sql already
-- contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/019_ingestion_runs.sql
BEGIN;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id          bigserial PRIMARY KEY,
    source_key      text NOT NULL,                 -- backend/app/connectors.py SOURCE_TYPES key
    data_name       text NOT NULL,                 -- what was read, e.g. 'Account'
    status          text NOT NULL CHECK (status IN ('success', 'failed')),
    rows_received   bigint NOT NULL DEFAULT 0,
    message         text,
    databricks_run  jsonb,                         -- {job_id, run_id} when known
    ran_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingestion_runs_recent_idx ON ingestion_runs (ran_at DESC);

COMMIT;
