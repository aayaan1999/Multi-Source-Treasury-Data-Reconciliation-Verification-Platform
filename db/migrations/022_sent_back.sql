-- Sent back (specs/reconciliation-approvals.md section 10): the last time a reconciliation task was sent back
-- to the team - by whom, when, from which step (CFO approval or run sign-off) and why - so the Tasks list
-- can mark it and the task can say why, whichever way it came back. Safe to run more than once.
-- db/schema.sql already contains this for fresh installs. Needs migration 021 first. Apply with:
--   python db/apply_migration.py db/migrations/022_sent_back.sql
BEGIN;

ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS sent_back_by integer REFERENCES users (user_id);
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS sent_back_at timestamptz;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS sent_back_from text CHECK (sent_back_from IN ('CFO_APPROVAL', 'RUN_SIGNOFF'));
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS sent_back_note text;

ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS sent_back_by integer REFERENCES users (user_id);
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS sent_back_at timestamptz;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS sent_back_from text CHECK (sent_back_from IN ('CFO_APPROVAL', 'RUN_SIGNOFF'));
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS sent_back_note text;

COMMIT;
