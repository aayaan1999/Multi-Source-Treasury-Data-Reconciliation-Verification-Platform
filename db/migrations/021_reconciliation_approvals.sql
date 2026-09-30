-- One approval model for reconciliation tasks (specs/reconciliation-approvals.md): the team decides
-- every task (a pipeline gap or a core-system break group), the CFO must approve important ones, and
-- the CFO signs off each run once every task in it is decided. Both task types run on the same
-- Camunda process (reconciliation-task); a run's sign-off runs on reconciliation-run-signoff.
--
--   * pipeline_reconciliation: the team's decision, who made it and when, whether the CFO must approve
--     (and why), and the run it belongs to; statuses for the new steps.
--   * reconciliation_groups: the same decision / CFO columns and run; AWAITING_CFO.
--   * reconciliation_corrections: a proposed fix can belong to a break group as well as a pipeline item;
--     WITHDRAWN for a fix the decision no longer uses.
--   * reconciliation_runs: one row per run of a source, with its sign-off.
--
-- Safe to run more than once. db/schema.sql already contains this for fresh installs. Needs
-- migrations 016 and 020 first. Apply with:
--   python db/apply_migration.py db/migrations/021_reconciliation_approvals.sql
BEGIN;

CREATE TABLE IF NOT EXISTS reconciliation_runs (
    run_id                bigserial PRIMARY KEY,
    source_system         text NOT NULL,              -- CORE_CSV (pipeline gaps), neon, salesforce (breaks)
    run_key               text NOT NULL,              -- the ingest batch, or the comparison date
    run_date              date NOT NULL,
    status                text NOT NULL DEFAULT 'OPEN'
                              CHECK (status IN ('OPEN', 'IN_SIGNOFF', 'SIGNED_OFF', 'SUPERSEDED')),
    process_instance_key  bigint,
    signed_by             integer REFERENCES users (user_id),
    signed_at             timestamptz,
    sign_note             text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_system, run_key)
);

ALTER TABLE pipeline_reconciliation DROP CONSTRAINT IF EXISTS pipeline_reconciliation_status_check;
ALTER TABLE pipeline_reconciliation ADD CONSTRAINT pipeline_reconciliation_status_check
    CHECK (status IN ('OPEN', 'MATCHED', 'WITH_TEAM', 'AWAITING_CFO', 'DECIDED', 'APPROVED', 'SUPERSEDED',
                      'WITH_CFO', 'ASSIGNED', 'SUBMITTED'));      -- the last three: the retired CFO-first process
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS decision text
    CHECK (decision IN ('ACCEPT', 'CORRECT', 'DISMISS'));
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS decided_by integer REFERENCES users (user_id);
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS decided_at timestamptz;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS cfo_required boolean NOT NULL DEFAULT false;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS cfo_reason text;
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS run_id bigint REFERENCES reconciliation_runs (run_id);
ALTER TABLE pipeline_reconciliation ADD COLUMN IF NOT EXISTS title text;      -- the task's one-line title, set when it starts

ALTER TABLE reconciliation_groups DROP CONSTRAINT IF EXISTS reconciliation_groups_status_check;
ALTER TABLE reconciliation_groups ADD CONSTRAINT reconciliation_groups_status_check
    CHECK (status IN ('PENDING', 'OPEN', 'AWAITING_CFO', 'CLOSED'));
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS decided_at timestamptz;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS approved_at timestamptz;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS cfo_required boolean NOT NULL DEFAULT false;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS cfo_reason text;
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS run_id bigint REFERENCES reconciliation_runs (run_id);
ALTER TABLE reconciliation_groups ADD COLUMN IF NOT EXISTS title text;

ALTER TABLE reconciliation_corrections ALTER COLUMN recon_id DROP NOT NULL;
ALTER TABLE reconciliation_corrections ADD COLUMN IF NOT EXISTS group_id bigint REFERENCES reconciliation_groups (group_id);
ALTER TABLE reconciliation_corrections DROP CONSTRAINT IF EXISTS reconciliation_corrections_owner_check;
ALTER TABLE reconciliation_corrections ADD CONSTRAINT reconciliation_corrections_owner_check
    CHECK ((recon_id IS NULL) <> (group_id IS NULL));
ALTER TABLE reconciliation_corrections DROP CONSTRAINT IF EXISTS reconciliation_corrections_status_check;
ALTER TABLE reconciliation_corrections ADD CONSTRAINT reconciliation_corrections_status_check
    CHECK (status IN ('PROPOSED', 'APPROVED', 'WITHDRAWN'));
CREATE UNIQUE INDEX IF NOT EXISTS reconciliation_corrections_one_per_group_field
    ON reconciliation_corrections (group_id, source_table, record_key, field_name) WHERE status = 'PROPOSED';

COMMIT;
