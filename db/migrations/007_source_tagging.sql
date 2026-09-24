-- Adds Notebook 1's source tags (specs/source-tagging.md, FLOW-1a in
-- project-docs/CLIENT-FEEDBACK-BACKLOG.md) to the 8 entity/time-series tables and
-- data_quality_exceptions: which source system sent each record, its country, the ingestion run
-- and the file. Nullable, so a load from an older Notebook 1 (no tags) still works; the load fills
-- them from the next run on. Safe to run more than once. db/schema.sql already contains this for
-- fresh installs.
--
-- Can be applied before or after the updated notebooks are deployed: the load copies only columns
-- present on both sides. Apply with:
--   python db/apply_migration.py db/migrations/007_source_tagging.sql
BEGIN;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['branches', 'customers', 'accounts', 'loans', 'transactions',
                             'capital_positions', 'liquidity_daily', 'fx_rates', 'data_quality_exceptions']
    LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS source_system text', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS source_country text', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS ingest_batch_id text', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS source_file text', t);
    END LOOP;
END $$;

COMMIT;
