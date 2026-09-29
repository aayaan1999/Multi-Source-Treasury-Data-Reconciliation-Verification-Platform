-- Step 1 of 3 - DEMO DATA ONLY. Run in the Neon SQL editor (the app's database) before 02.
--
-- Saves the daily KPI rows exactly as they are, so 99_restore.sql can put them back.
-- Safe to run more than once: an existing backup is kept, never overwritten (the first one is the original).

CREATE TABLE IF NOT EXISTS kpi_daily_summary_backup AS
SELECT * FROM kpi_daily_summary;

-- Check: the backup has the same rows as the live table (the first time you run it).
SELECT (SELECT count(*) FROM kpi_daily_summary)        AS live_rows,
       (SELECT count(*) FROM kpi_daily_summary_backup) AS backup_rows;
