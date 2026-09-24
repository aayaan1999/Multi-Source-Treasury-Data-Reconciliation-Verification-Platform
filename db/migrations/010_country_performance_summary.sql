-- Adds country_performance_summary (specs/cfo-country-view.md, FLOW-4): the CFO dashboard's
-- per-country view, a Notebook 6 Gold snapshot in USD, loaded like the other snapshot tables. Safe to
-- run more than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/010_country_performance_summary.sql
BEGIN;

CREATE TABLE IF NOT EXISTS country_performance_summary (
    calculation_date        date NOT NULL,
    country                 text NOT NULL,
    customer_count          bigint,
    deposits_usd            double precision,
    loans_usd               double precision,
    npl_loans_usd           double precision,
    npl_ratio_pct           double precision,
    transaction_count       bigint,
    transaction_volume_usd  double precision,
    PRIMARY KEY (calculation_date, country)
);

COMMIT;
