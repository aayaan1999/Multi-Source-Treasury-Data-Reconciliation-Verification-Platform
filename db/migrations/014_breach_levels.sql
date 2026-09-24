-- Breach levels (client point 8: BRC-1..4, specs/breach-levels.md). Each limit gets three levels:
-- early warning (notification only), internal appetite (threshold_value, a task) and regulatory
-- (an urgent task), plus a consecutive-days rule; each breach records its level and due date. Seeds a
-- limit for every KPI tile from the dashboard's former built-in thresholds (amber = early warning,
-- red = appetite, limit line = regulatory), filling only values not already set, so an existing
-- limit's threshold is kept. All placeholders until the bank gives official values. Safe to run more
-- than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/014_breach_levels.sql
BEGIN;

ALTER TABLE limits ADD COLUMN IF NOT EXISTS early_warning_value double precision;
ALTER TABLE limits ADD COLUMN IF NOT EXISTS regulatory_value double precision;
ALTER TABLE limits ADD COLUMN IF NOT EXISTS consecutive_days integer NOT NULL DEFAULT 1;
ALTER TABLE limits ADD COLUMN IF NOT EXISTS is_placeholder boolean NOT NULL DEFAULT true;

ALTER TABLE breaches ADD COLUMN IF NOT EXISTS level text NOT NULL DEFAULT 'APPETITE';
ALTER TABLE breaches ADD COLUMN IF NOT EXISTS due_date date;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'breaches_level_check') THEN
        ALTER TABLE breaches ADD CONSTRAINT breaches_level_check CHECK (level IN ('EARLY_WARNING', 'APPETITE', 'REGULATORY'));
    END IF;
END $$;

-- metric_name, early warning, appetite (threshold_value), regulatory, direction, resolution days
INSERT INTO limits (metric_name, early_warning_value, threshold_value, regulatory_value, direction, resolution_days) VALUES
    ('capital_adequacy_ratio',   15,   12.5, 12,   'BELOW', 14),
    ('liquidity_coverage_ratio', 120,  100,  100,  'BELOW', 7),
    ('npl_ratio',                3,    5,    NULL, 'ABOVE', 30),
    ('net_interest_margin',      2.5,  1.5,  NULL, 'BELOW', 30),
    ('cost_to_income_ratio',     50,   60,   NULL, 'ABOVE', 30),
    ('return_on_equity',         10,   5,    NULL, 'BELOW', 30),
    ('dollarization_ratio',      50,   70,   NULL, 'ABOVE', 30)
ON CONFLICT (metric_name) DO UPDATE SET
    early_warning_value = COALESCE(limits.early_warning_value, EXCLUDED.early_warning_value),
    regulatory_value    = COALESCE(limits.regulatory_value, EXCLUDED.regulatory_value);

COMMIT;
