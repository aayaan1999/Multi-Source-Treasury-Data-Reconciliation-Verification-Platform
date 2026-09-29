-- Undo - puts back the daily KPI rows saved by 01_backup.sql. Run in the Neon SQL editor (the app's database).
--
-- Replaces every day up to the last day in the backup with the saved rows. Days the pipeline added after the
-- backup was taken are kept.

BEGIN;

DELETE FROM kpi_daily_summary
WHERE calculation_date <= (SELECT max(calculation_date) FROM kpi_daily_summary_backup);

INSERT INTO kpi_daily_summary
SELECT * FROM kpi_daily_summary_backup;

COMMIT;

-- Check: the rows are the saved ones again.
SELECT calculation_date, round(car_pct::numeric, 2) AS car_pct, round(npl_ratio_pct::numeric, 2) AS npl_pct
FROM kpi_daily_summary
ORDER BY calculation_date;

-- When you no longer need the backup:
-- DROP TABLE kpi_daily_summary_backup;
