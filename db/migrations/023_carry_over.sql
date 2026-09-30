-- Early-morning sign-off with carry-over (specs/reconciliation-approvals.md section 10): at the 08:00 cut-off the
-- CFO signs off the decided tasks of a run, and the tasks still open are carried into the next day's run with a
-- high priority; a task carried 3 times is escalated. Safe to run more than once. db/schema.sql already
-- contains this for fresh installs. Needs migration 022 first. Apply with:
--   python db/apply_migration.py db/migrations/023_carry_over.sql
BEGIN;

-- How many sign-offs a task has been carried past, since which run date, and when it was escalated.
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS carried_count integer NOT NULL DEFAULT 0;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS carried_since date;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS escalated_at timestamptz;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS carried_count integer NOT NULL DEFAULT 0;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS carried_since date;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS escalated_at timestamptz;

-- What a sign-off covered: the tasks it signed off, the tasks it carried, and the run they went to.
ALTER TABLE reconciliation_runs ADD COLUMN IF NOT EXISTS signed_tasks integer;
ALTER TABLE reconciliation_runs ADD COLUMN IF NOT EXISTS carried_tasks integer;
ALTER TABLE reconciliation_runs ADD COLUMN IF NOT EXISTS carried_to_run_id bigint REFERENCES reconciliation_runs (run_id);

INSERT INTO app_settings (key, value, description) VALUES
    ('recon.signoff',
     '{"cutoff_time": "08:00", "utc_offset_hours": 3, "carry_limit": 3}',
     'Run sign-off: from the cut-off (bank time, UTC + offset) on the day after a run, the CFO can sign off its decided tasks and carry the open ones to the next day; a task carried carry_limit times is escalated')
ON CONFLICT (key) DO NOTHING;

COMMIT;
