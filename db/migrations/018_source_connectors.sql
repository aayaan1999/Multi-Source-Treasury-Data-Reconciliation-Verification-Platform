-- Source connectors for the Data Ingestion screen (specs/screen-data-ingestion.md, backlog ING-1):
-- which sources are connected and their NON-SECRET settings (instance URL, bucket, host...). Passwords,
-- keys and tokens are never stored here: they go to the Databricks secret scope bank-data-sources, or
-- nowhere when the app isn't connected to Databricks (credentials = 'not_stored').
-- Safe to run more than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/018_source_connectors.sql
BEGIN;

CREATE TABLE IF NOT EXISTS source_connectors (
    source_key     text PRIMARY KEY,
    config         jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_fields  text[] NOT NULL DEFAULT '{}',     -- names of the secrets supplied, never their values
    credentials    text NOT NULL CHECK (credentials IN ('databricks', 'not_stored', 'none_needed')),
    connected_by   integer REFERENCES users (user_id),
    connected_at   timestamptz NOT NULL DEFAULT now(),
    last_sync_at   timestamptz
);

COMMIT;
