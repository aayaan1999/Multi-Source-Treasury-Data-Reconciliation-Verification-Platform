-- Adds pipeline_reconciliation (specs/pipeline-reconciliation.md, FLOW-3 in
-- project-docs/CLIENT-FEEDBACK-BACKLOG.md): one row per run + source + country + table, comparing
-- what the source sent with what survived cleaning. Loaded insert-only by load_to_postgres.py;
-- status is owned by the application after first load (FLOW-5). Safe to run more than once.
-- db/schema.sql already contains this for fresh installs.
--
-- Can be applied before or after the job is deployed: until this table exists, the load skips it
-- (the items stay in Delta and load on the first run after this is applied). Apply with:
--   python db/apply_migration.py db/migrations/008_pipeline_reconciliation.sql
BEGIN;

CREATE TABLE IF NOT EXISTS pipeline_reconciliation (
    recon_id                bigserial PRIMARY KEY,
    recon_key               text NOT NULL UNIQUE,
    ingest_batch_id         text NOT NULL,
    source_system           text NOT NULL,
    source_country          text NOT NULL,
    source_table            text NOT NULL,
    received_rows           bigint NOT NULL,
    clean_rows              bigint NOT NULL,
    rejected_rows           bigint NOT NULL,
    amount_column           text,
    unreadable_amount_rows  bigint NOT NULL DEFAULT 0,
    amounts_by_currency     jsonb,
    has_gap                 boolean NOT NULL,
    status                  text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'MATCHED')),
    detected_at             timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS pipeline_reconciliation_source_idx
    ON pipeline_reconciliation (source_system, detected_at DESC);

COMMIT;
