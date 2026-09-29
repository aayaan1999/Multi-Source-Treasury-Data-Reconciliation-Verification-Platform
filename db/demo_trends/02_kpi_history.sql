-- Step 2 of 3 - DEMO DATA ONLY. Run in the Neon SQL editor (the app's database) after 01_backup.sql.
--
-- Why: the pipeline has re-read the same landing files since 28 Sep, so every day's KPIs are identical and the
-- dashboard's trend lines are flat, with a jump on 24 Sep where an earlier, different demo dataset stops.
--
-- What it does: keeps the LATEST day (the real pipeline result) and replaces every earlier day with about six
-- weeks of business days (Mon-Fri) that lead smoothly into it. The values are demonstration figures, not
-- measured ones, but they are kept consistent with the data behind the KPI detail pages:
--   * Liquidity (LCR): on days that have a liquidity_daily row it is exactly HQLA / net outflows, as the
--     pipeline calculates it; other days follow the same level.
--   * Capital ratio (CAR): follows the real monthly capital_positions trend (about 12.6% in August rising to
--     today's value), with small day-to-day moves.
--   * Bad loans (NPL): climbs about 0.9 points over the period and crosses the 5% limit around ten business
--     days before the latest day, so the breach alert has a history.
--   * Total assets grow about 5%; NIM, cost-to-income, ROE and dollarization drift slightly.
-- Deterministic: running it again gives exactly the same numbers.
--
-- What it doesn't change: the latest day, any other table, or the raw data. The KPI detail "how this was
-- calculated" drill-down describes the latest day only, which is still the real one.
--
-- Afterwards: the pipeline replaces only the day it runs for, so these rows stay. But until new landing files
-- are uploaded, each new day's run repeats the latest values again (see the note at the end).

BEGIN;

DROP TABLE IF EXISTS pg_temp.kpi_latest, pg_temp.kpi_days;      -- safe to run again in the same session

CREATE TEMP TABLE kpi_latest ON COMMIT DROP AS
SELECT * FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT 1;

CREATE TEMP TABLE kpi_days ON COMMIT DROP AS
SELECT d::date AS day,
       (row_number() OVER (ORDER BY d) - 1)::int AS t            -- 0 = oldest day
FROM kpi_latest l,
     generate_series(l.calculation_date - 44, l.calculation_date - 1, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;                                -- business days only

-- Every day before the latest one is replaced.
DELETE FROM kpi_daily_summary
WHERE calculation_date < (SELECT calculation_date FROM kpi_latest);

INSERT INTO kpi_daily_summary (calculation_date, car_pct, lcr_pct, npl_ratio_pct, total_assets_usd,
                               dollarization_ratio_pct, nim_pct, cost_to_income_pct, roe_pct, assumptions_applied)
SELECT d.day,
       -- r = how far back the day is (1 = oldest, 0 = the latest day)
       l.car_pct - 0.25 * r + 0.04 * sin(d.t * 1.3),
       coalesce(100 * ld.hqla / nullif(ld.net_outflows_30d, 0),
                l.lcr_pct + 5.0 * r + 3.0 * sin(d.t * 0.9) + 1.2 * cos(d.t * 2.1)),
       l.npl_ratio_pct - 0.95 * r + 0.06 * sin(d.t * 1.7),
       l.total_assets_usd * (1 - 0.05 * r + 0.004 * sin(d.t * 0.8)),
       least(l.dollarization_ratio_pct - 0.8 * r + 0.05 * sin(d.t * 1.2), 100),
       l.nim_pct + 0.11 * r + 0.03 * sin(d.t * 1.1),
       l.cost_to_income_pct + 1.5 * r + 0.6 * sin(d.t * 0.7),
       l.roe_pct + 0.16 * r + 0.05 * sin(d.t * 1.9),
       l.assumptions_applied
FROM kpi_days d
CROSS JOIN kpi_latest l
CROSS JOIN LATERAL (SELECT 1 - d.t::float / (SELECT max(t) FROM kpi_days) AS r) AS back
LEFT JOIN liquidity_daily ld ON ld.date = d.day;

COMMIT;

-- Check: one row per business day, moving each day, ending in the real latest day.
SELECT calculation_date,
       round(car_pct::numeric, 2)                  AS car_pct,
       round(lcr_pct::numeric, 1)                  AS lcr_pct,
       round(npl_ratio_pct::numeric, 2)            AS npl_pct,
       round((total_assets_usd / 1e6)::numeric, 1) AS assets_musd
FROM kpi_daily_summary
ORDER BY calculation_date;

-- Note: the next pipeline run for a NEW day, with the same landing files, adds a row identical to the latest
-- one. To keep the line moving, upload new day files (scripts/generate_next_day.py) before each run.
