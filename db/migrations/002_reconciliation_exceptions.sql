-- Adds reconciliation_exceptions (specs/multi-source-reconciliation.md) to a database that was
-- created from an earlier db/schema.sql. Safe to run more than once. db/schema.sql already
-- contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/002_reconciliation_exceptions.sql
BEGIN;

CREATE TABLE IF NOT EXISTS reconciliation_exceptions (
    exception_id      bigserial PRIMARY KEY,
    source_system     text NOT NULL,
    entity_type       text NOT NULL,
    entity_id         text NOT NULL,
    field_name        text,
    source_value      text,
    canonical_value   text,
    mismatch_type     text NOT NULL CHECK (mismatch_type IN
                          ('VALUE_MISMATCH', 'MISSING_IN_CANONICAL', 'MISSING_IN_SOURCE')),
    status            text NOT NULL DEFAULT 'OPEN' CHECK (status IN
                          ('OPEN', 'ACCEPTED', 'CORRECTED', 'DISMISSED')),
    detected_at       timestamptz NOT NULL,
    resolved_by       integer REFERENCES users (user_id),
    resolved_at       timestamptz,
    resolution_note   text,
    UNIQUE (source_system, entity_type, entity_id, mismatch_type, field_name)
);

COMMIT;
