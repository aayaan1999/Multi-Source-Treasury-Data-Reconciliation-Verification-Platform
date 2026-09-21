-- Adds what screens 3 (regulatory reporting) and 4 (scenario modelling) need, to a database that was created
-- from an earlier db/schema.sql. Safe to run more than once. db/schema.sql already contains all of this for
-- fresh installs. Apply with:  python db/apply_migration.py db/migrations/001_screens_2_to_5.sql
BEGIN;

ALTER TABLE report_definitions ADD COLUMN IF NOT EXISTS owner_department text;
ALTER TABLE report_definitions ADD COLUMN IF NOT EXISTS template_format text;

ALTER TABLE report_line_items ADD COLUMN IF NOT EXISTS section text NOT NULL DEFAULT '';
ALTER TABLE report_line_items ADD COLUMN IF NOT EXISTS display_order integer NOT NULL DEFAULT 0;
ALTER TABLE report_line_items ADD COLUMN IF NOT EXISTS line_kind text NOT NULL DEFAULT 'input'
    CHECK (line_kind IN ('input', 'subtotal', 'total', 'ratio'));
ALTER TABLE report_line_items ADD COLUMN IF NOT EXISTS unit text NOT NULL DEFAULT 'currency'
    CHECK (unit IN ('currency', 'percent'));
ALTER TABLE report_line_items ADD COLUMN IF NOT EXISTS is_demo_input boolean NOT NULL DEFAULT false;

ALTER TABLE calculation_audit ADD COLUMN IF NOT EXISTS notes text;

ALTER TABLE validation_rules ADD COLUMN IF NOT EXISTS rule_key text;
CREATE UNIQUE INDEX IF NOT EXISTS validation_rules_key_idx ON validation_rules (report_id, rule_key);

CREATE TABLE IF NOT EXISTS saved_scenarios (
    scenario_id  serial PRIMARY KEY,
    name         text NOT NULL,
    inputs       jsonb NOT NULL,
    assumptions  jsonb NOT NULL,
    outputs      jsonb NOT NULL,
    created_by   integer REFERENCES users (user_id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

COMMIT;
