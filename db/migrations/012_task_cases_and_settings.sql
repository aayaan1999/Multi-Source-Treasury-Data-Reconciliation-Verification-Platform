-- Task cases, severity, deadlines (specs/task-cases.md, client point 6) and the shared app_settings
-- table (also used by points 5 and 8). Seeds placeholder defaults without overwriting values already
-- changed. Safe to run more than once.
-- db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/012_task_cases_and_settings.sql
BEGIN;

CREATE TABLE IF NOT EXISTS app_settings (
    key             text PRIMARY KEY,
    value           jsonb NOT NULL,
    description     text NOT NULL,
    is_placeholder  boolean NOT NULL DEFAULT true,   -- true until the bank confirms the value
    updated_at      timestamptz NOT NULL DEFAULT now()
);

INSERT INTO app_settings (key, value, description) VALUES
    ('task.severity',
     '{"base": {"SUSPICIOUS": 3, "THRESHOLD": 2, "OPERATIONAL": 1}, "many_flags_at": 3, "many_rules_at": 2, "high_min": 4, "medium_min": 2}',
     'How a case''s severity is scored: base by flag type, +1 for many flags, +1 for several rules; High/Medium become tasks, Low goes to the daily digest'),
    ('task.due_days',
     '{"HIGH": 2, "MEDIUM": 5, "LOW": 10, "DATA_QUALITY": 5, "RECONCILIATION": 3}',
     'Days to resolve a task, by case severity or task type (breaches use their limit''s resolution_days)')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS task_cases (
    case_id               bigserial PRIMARY KEY,
    account_id            text NOT NULL,
    case_date             date NOT NULL,
    flag_type             text NOT NULL,
    team                  text NOT NULL,
    severity              text NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM', 'LOW')),
    severity_score        integer NOT NULL,
    flag_count            integer NOT NULL,
    due_date              date NOT NULL,
    status                text NOT NULL CHECK (status IN ('PENDING', 'OPEN', 'DIGEST', 'CLOSED')),
    outcome               text,
    process_instance_key  bigint,
    created_at            timestamptz NOT NULL DEFAULT now(),
    closed_at             timestamptz
);

CREATE TABLE IF NOT EXISTS task_case_flags (
    case_id         bigint NOT NULL REFERENCES task_cases (case_id),
    transaction_id  text NOT NULL,
    flag_label      text NOT NULL,
    PRIMARY KEY (transaction_id, flag_label)          -- a flag is only ever in one case
);

CREATE INDEX IF NOT EXISTS task_case_flags_case_idx ON task_case_flags (case_id);

COMMIT;
