# Spec: Pipeline Job (file-arrival trigger) and Load to Neon Postgres

**Status:** Deployed and verified live on Databricks/Neon (2026-09-22) via `databricks bundle
deploy`. Fixed one real bug found by the live run: the staging write in `load_to_postgres.py` used
generic `format("jdbc")`, which this workspace's serverless compute rejects
(`UNSUPPORTED_DATA_SOURCE_WRITE`); switched to Databricks' bundled `postgresql` Spark format.
**Files:** `databricks.yml`, `notebooks/load_to_postgres.py`, `db/apply_schema.py`, `db/test_load_logic.py`
**Depends on:** notebooks 1-6 (verified on Databricks), `db/schema.sql`, `specs/postgres-schema.md`
**Supersedes:** the "nightly import job" wording in `CLAUDE.md` / `specs/postgres-schema.md` — the pipeline is now
event-driven (starts when a file lands), with the Postgres load as its last task.

---

## 1. Objective

When someone uploads the source CSVs, the whole pipeline runs by itself and the application database on Neon is
refreshed, so the dashboards show the new numbers minutes later with no manual step.

## 2. Flow

```
CSV(s) uploaded to /Volumes/dbw_bankx_treasury_poc/raw/raw/resources
        │  file-arrival trigger (waits 2 min after the last file, max one run per 5 min)
        ▼
  ingest (NB1) ─► quality (NB2) ─┬─► kpi_summary (NB3)
                                 ├─► exception_summary (NB4)     ─► load_postgres ─► Neon
                                 ├─► fraud_rules (NB5)
                                 └─► portfolio_snapshot (NB6)
```

* Neon Postgres is the application database (FastAPI reads it). Databricks connects over JDBC with SSL.
* A run that starts while another is in progress is queued, not run in parallel (`max_concurrent_runs: 1`).
* "Real time" here means **minutes after upload** (serverless start-up + six notebooks + load), not per row. The FX
  rate is the only live value: notebooks 3, 5 and 6 fetch it when they run.

## 3. Load rules (load notebook)

Each Delta table is written to a throwaway `staging` schema over JDBC; then **one Postgres transaction** merges into
`public` (all-or-nothing, so a dashboard never reads a half-loaded state); then `staging` is dropped.

| Group | Tables | Rule |
|---|---|---|
| Entity / time series | branches, customers, accounts, loans, transactions, capital_positions, liquidity_daily, fx_rates | Full refresh. Deleted children-first, inserted parents-first so foreign keys hold |
| Gold snapshots | kpi_daily_summary, exception_summary_*, loan_*, ltv_distribution, *_performance_summary, top_exposures, scenario_snapshot | Replace the rows of the latest `calculation_date` only; older dates are kept |
| Exceptions | data_quality_exceptions | Upsert on `(source_table, record_key, flag_label)` so `exception_id` stays stable; delete rows no longer present. Records with no key get a `(no key #n)` placeholder |
| Fraud flags | flagged_transactions | **Insert-only** (`ON CONFLICT DO NOTHING`) — `status` belongs to the app after review, a reload must never reset it |
| FX audit | fx_rate_usage_log | Full mirror of the append-only Delta log |

Column lists are read from Postgres: every target column also present in staging is copied and cast to the
target type; extra Delta columns and app-only columns (`exception_id`) need no config. Map columns are sent as JSON
text and cast to `jsonb`.

## 4. One-time setup

1. **Neon:** create a project and database; copy the connection details from the console.
2. **Apply the schema:** set `DATABASE_URL` (Neon connection string, `sslmode=require`) and run
   `python db/apply_schema.py`. It refuses to run if the schema is already there.
3. **Databricks secrets** (scope `neon`, keys `host`, `database`, `user`, `password`):
   `databricks secrets create-scope neon`, then `databricks secrets put-secret neon <key> --string-value <value>`.
   Never put these in the repo or a notebook.
4. **Deploy the job:** from the repo root, `databricks bundle validate` then `databricks bundle deploy`.
5. **Test:** upload the 8 CSVs to the landing folder and watch **Workflows → bank-data-pipeline**.

## 5. Acceptance criteria

- [x] Merge logic runs on a real PostgreSQL 16.2 with `db/schema.sql`: `python db/test_load_logic.py` — 20 checks pass
      (type casts incl. `text[]` and `jsonb`, reviewed `status` survives a reload, stale exceptions removed with stable
      `exception_id`, KPI history kept, same-date reload replaces, an orphan child fails the load and rolls back
      everything)
- [x] `databricks.yml` parses (CLI reaches the authentication step; **not** validated against a workspace)
- [ ] `databricks bundle validate` and `deploy` succeed against the workspace
- [ ] Uploading files starts exactly one run (the 2-minute quiet period groups the 8 files)
- [ ] Serverless load notebook connects to Neon over JDBC (`%pip install psycopg2-binary` and the JDBC driver both work)
- [ ] After a run, every Neon table's row count matches its Delta source (the notebook's final cell asserts this)
- [ ] A second run with the same files leaves Neon unchanged apart from `calculation_date`-stamped rows
- [ ] Neon cold start (suspended database) is absorbed by the connect retry

## 6. Known risks and limits

* **Serverless JDBC is unverified.** If serverless blocks the Postgres JDBC write, give `load_postgres` a job cluster.
* **Duplicate keys fail the load.** Notebook 2 does not check duplicate primary keys (e.g. two rows with the same
  `customer_id`), so real data with duplicates makes the Postgres insert fail — loudly and with a full rollback, which
  is the right outcome, but the fix belongs in Notebook 2.
* **Null `stage`** passes Notebook 2 and would land in `loan_stage_summary`, whose Postgres key includes `stage`.
  Not present in the sample data.
* **Input is CSV only.** The trigger fires on any file in the folder, including a non-CSV or a partial upload; a
  missing CSV makes Notebook 1 fail and stops the run before anything is loaded.
* **Neon free tier** limits storage (~0.5 GB) and suspends idle databases; the staging schema is dropped after each
  load to save space.
* Postgres row-level security is still not defined (`specs/postgres-schema.md` section 3).
