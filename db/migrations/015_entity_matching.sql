-- Duplicate companies (client point 3: DUP-1..4, specs/entity-matching.md): candidate pairs of
-- customer records that may be the same entity, a person's decision on each, and the resulting
-- customer -> group link that exposure totals roll up by. App-owned tables with no foreign key to
-- customers (the nightly load fully replaces customers). Seeds matching settings; allows
-- 'entity_match' tasks in camunda_process_tracking; adds a deadline for them. Needs migration 012.
-- Safe to run more than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/015_entity_matching.sql
BEGIN;

CREATE TABLE IF NOT EXISTS entity_match_candidates (
    candidate_id          bigserial PRIMARY KEY,
    customer_a            text NOT NULL,
    customer_b            text NOT NULL,
    name_a                text NOT NULL,
    name_b                text NOT NULL,
    score                 double precision NOT NULL,
    reasons               text[] NOT NULL,
    status                text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CONFIRMED', 'REJECTED')),
    process_instance_key  bigint,
    created_at            timestamptz NOT NULL DEFAULT now(),
    decided_by            integer REFERENCES users (user_id),
    decided_at            timestamptz,
    CHECK (customer_a < customer_b),
    UNIQUE (customer_a, customer_b)
);

-- Rebuilt from CONFIRMED pairs after every decision: each linked customer -> its group's lead record.
CREATE TABLE IF NOT EXISTS customer_entity (
    customer_id         text PRIMARY KEY,
    master_customer_id  text NOT NULL
);

-- Top exposures list the confirmed duplicates folded into each row (Notebook 6).
ALTER TABLE top_exposures ADD COLUMN IF NOT EXISTS linked_customer_ids text;

INSERT INTO app_settings (key, value, description) VALUES
    ('dedup.matching',
     '{"min_score": 0.85, "legal_words": ["SAL", "SARL", "SAE", "LTD", "LIMITED", "INC", "LLC", "PVT", "PLC", "CO", "COMPANY", "CORP", "CORPORATION", "WLL", "FZE", "FZCO"], "abbreviations": {"TCS": "TATA CONSULTANCY SERVICES"}}',
     'How possible duplicate customers are found: names compared after removing legal words (and expanding known abbreviations); pairs at or above min_score become a review task')
ON CONFLICT (key) DO NOTHING;

UPDATE app_settings SET value = value || '{"DUPLICATE": 10}'::jsonb
WHERE key = 'task.due_days' AND NOT value ? 'DUPLICATE';

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
    CHECK (record_type IN ('data_quality', 'fraud', 'breach', 'reconciliation', 'entity_match'));

COMMIT;
