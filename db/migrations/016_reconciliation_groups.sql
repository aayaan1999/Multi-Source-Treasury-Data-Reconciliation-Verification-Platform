-- Core-system reconciliation redesign (client point 1: REC-1..5, 7, 8, specs/reconciliation-groups.md):
-- automatic clearing, grouping breaks by cause into tasks, safety rules, ageing / recurring breaks,
-- and run sign-off. Also fixes a real bug: missing-record breaks have field_name NULL, which the old
-- UNIQUE treated as always distinct, so every load re-inserted them - duplicates are removed (keeping
-- the oldest row, which carries any reviewer decision) and the key now treats NULLs as equal.
-- Needs migration 012 (app_settings). Safe to run more than once. db/schema.sql already contains this
-- for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/016_reconciliation_groups.sql
BEGIN;

-- 1. The duplicate fix.
DELETE FROM reconciliation_exceptions r USING reconciliation_exceptions k
WHERE r.field_name IS NULL AND k.field_name IS NULL AND r.exception_id > k.exception_id
  AND r.source_system = k.source_system AND r.entity_type = k.entity_type
  AND r.entity_id = k.entity_id AND r.mismatch_type = k.mismatch_type;

DO $$
DECLARE
    con text;
BEGIN
    FOR con IN SELECT conname FROM pg_constraint
               WHERE conrelid = 'reconciliation_exceptions'::regclass AND contype IN ('u', 'c')
                 AND (pg_get_constraintdef(oid) LIKE 'UNIQUE (source_system%' OR pg_get_constraintdef(oid) LIKE '%status%')
    LOOP
        EXECUTE format('ALTER TABLE reconciliation_exceptions DROP CONSTRAINT %I', con);
    END LOOP;
END $$;

ALTER TABLE reconciliation_exceptions DROP CONSTRAINT IF EXISTS reconciliation_exceptions_break_key;
ALTER TABLE reconciliation_exceptions ADD CONSTRAINT reconciliation_exceptions_break_key
    UNIQUE NULLS NOT DISTINCT (source_system, entity_type, entity_id, mismatch_type, field_name);
ALTER TABLE reconciliation_exceptions ADD CONSTRAINT reconciliation_exceptions_status_check
    CHECK (status IN ('OPEN', 'ACCEPTED', 'CORRECTED', 'DISMISSED', 'AUTO_ACCEPTED'));

-- 2. Per-break columns: the rule that cleared it, its group, ageing and recurrence.
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS resolved_rule text;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS group_id bigint;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS first_seen timestamptz;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS last_seen timestamptz;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS times_seen integer NOT NULL DEFAULT 1;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS recurring boolean NOT NULL DEFAULT false;
ALTER TABLE reconciliation_exceptions ADD COLUMN IF NOT EXISTS carved_out boolean NOT NULL DEFAULT false;
UPDATE reconciliation_exceptions SET first_seen = detected_at WHERE first_seen IS NULL;
UPDATE reconciliation_exceptions SET last_seen = detected_at WHERE last_seen IS NULL;

-- 3. Groups: breaks with the same cause, decided as one task.
CREATE TABLE IF NOT EXISTS reconciliation_groups (
    group_id                  bigserial PRIMARY KEY,
    group_key                 text NOT NULL,
    source_system             text NOT NULL,
    entity_type               text NOT NULL,
    field_name                text,
    mismatch_type             text NOT NULL,
    pattern                   text NOT NULL,
    important                 boolean NOT NULL DEFAULT false,
    break_count               integer NOT NULL,
    total_difference          double precision,
    largest_difference        double precision,
    requires_second_approval  boolean NOT NULL DEFAULT false,
    team                      text NOT NULL,
    status                    text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'OPEN', 'CLOSED')),
    decision                  text,
    due_date                  date NOT NULL,
    process_instance_key      bigint,
    created_at                timestamptz NOT NULL DEFAULT now(),
    decided_by                integer REFERENCES users (user_id),
    approved_by               integer REFERENCES users (user_id),
    closed_at                 timestamptz
);

-- 4. Run sign-off: one row per source system per day, prepared by one person, signed off by another.
CREATE TABLE IF NOT EXISTS reconciliation_signoffs (
    run_date       date NOT NULL,
    source_system  text NOT NULL,
    status         text NOT NULL CHECK (status IN ('SUBMITTED', 'SIGNED_OFF', 'RETURNED')),
    prepared_by    integer REFERENCES users (user_id),
    prepared_at    timestamptz,
    prepare_note   text,
    signed_by      integer REFERENCES users (user_id),
    signed_at      timestamptz,
    sign_note      text,
    PRIMARY KEY (run_date, source_system)
);

-- 5. Rules and deadlines (placeholders until the bank confirms).
INSERT INTO app_settings (key, value, description) VALUES
    ('recon.rules',
     '{"important_amount": 10000, "important_fields": ["name", "currency", "type", "segment"], "size_bands": [100, 1000, 10000], "same_difference_min": 3, "max_group_size": 1000, "second_approval_total": 100000, "owner_team": "OPERATIONS"}',
     'Core-system reconciliation: which breaks are always individual (amount, key fields, missing records), how the rest are grouped by cause, the total above which a bulk decision needs a second approver, and the owning team')
ON CONFLICT (key) DO NOTHING;

UPDATE app_settings SET value = value || '{"RECON_GROUP": 3}'::jsonb
WHERE key = 'task.due_days' AND NOT value ? 'RECON_GROUP';

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
    CHECK (record_type IN ('data_quality', 'fraud', 'breach', 'reconciliation', 'entity_match', 'recon_group'));

COMMIT;
