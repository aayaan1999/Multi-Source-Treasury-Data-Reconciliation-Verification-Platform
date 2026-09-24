# Databricks notebook source
# MAGIC %md
# MAGIC # Load to Postgres (Neon)
# MAGIC
# MAGIC Final task of the pipeline job. Copies the Silver/Gold Delta tables into the application
# MAGIC database on Neon so the FastAPI backend and dashboards can read them, per
# MAGIC `specs/pipeline-job-and-neon-load.md`.
# MAGIC
# MAGIC How it works: each Delta table is written over JDBC into a throwaway `staging` schema, then
# MAGIC **one Postgres transaction** merges staging into `public` — so a dashboard never sees a
# MAGIC half-loaded state — and finally the staging schema is dropped.
# MAGIC
# MAGIC Merge rules per table group (see the `MERGE HELPERS` cell):
# MAGIC * entity / time-series tables — full refresh (delete children first, insert parents first)
# MAGIC * Gold snapshot tables — replace the rows for the latest `calculation_date` only
# MAGIC * `data_quality_exceptions` — upsert, then delete rows no longer present
# MAGIC * `flagged_transactions` — insert new rows only; **never overwrites `status`**, which the
# MAGIC   application changes after review
# MAGIC * `fx_rate_usage_log` — full refresh from the append-only Delta log
# MAGIC
# MAGIC Needs a Databricks secret scope `neon` with keys `host`, `database`, `user`, `password`.

# COMMAND ----------

# MAGIC %pip install psycopg2-binary

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# Same catalog/schema pin as every other notebook, so bare Delta table names resolve identically.
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Merge helpers
# MAGIC
# MAGIC Plain psycopg2 + SQL, no Spark, so `db/test_load_logic.py` can run this exact cell against a
# MAGIC local Postgres. Column lists are read from Postgres itself: every target column that also
# MAGIC exists in the staging table is copied and cast to the target's type, so extra Delta columns
# MAGIC and app-side columns (e.g. `exception_id`) need no special handling.

# COMMAND ----------

# MERGE HELPERS
import time
import psycopg2

# (delta table, postgres table), parents before children — foreign keys in db/schema.sql.
ENTITY_TABLES = [
    ("branches_clean", "branches"),
    ("customers_clean", "customers"),
    ("accounts_clean", "accounts"),
    ("loans_clean", "loans"),
    ("transactions_clean", "transactions"),
    ("capital_positions_clean", "capital_positions"),
    ("liquidity_daily_clean", "liquidity_daily"),
    ("fx_rates_clean", "fx_rates"),
]

# Gold tables: same name in Delta and Postgres, every row carries calculation_date.
SNAPSHOT_TABLES = [
    "kpi_daily_summary",
    "exception_summary_by_flag",
    "exception_summary_by_table",
    "loan_breakdown_by_dimension",
    "loan_stage_summary",
    "top_exposures",
    "loan_ageing_summary",
    "ltv_distribution",
    "branch_performance_summary",
    "segment_performance_summary",
    "product_performance_summary",
    "scenario_snapshot",
]


def _columns(cur, qualified_table):
    """[(column, postgres type)] in table order."""
    cur.execute(
        """SELECT a.attname, format_type(a.atttypid, a.atttypmod)
           FROM pg_attribute a
           WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
           ORDER BY a.attnum""",
        (qualified_table,),
    )
    return cur.fetchall()


def _insert_from_staging(cur, table, tail=""):
    """INSERT INTO public.<table> SELECT <cast columns> FROM staging.<table> [tail]; returns rowcount."""
    staged = {name for name, _ in _columns(cur, f"staging.{table}")}
    cols = [(n, t) for n, t in _columns(cur, f"public.{table}") if n in staged]
    names = ", ".join(f'"{n}"' for n, _ in cols)
    exprs = ", ".join(f'"{n}"::{t}' for n, t in cols)
    cur.execute(f'INSERT INTO public."{table}" ({names}) SELECT {exprs} FROM staging."{table}" {tail}')
    return cur.rowcount


def run_merge(cur):
    """Merges every staged table into public. Caller owns the transaction (commit/rollback).
    Returns {postgres_table: rows written}."""
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'staging'")
    staged = {r[0] for r in cur.fetchall()}
    written = {}

    # 1. Entity / time-series tables: full refresh. Children are deleted before parents and parents
    #    inserted before children so the foreign keys hold at every step.
    entities = [pg for _, pg in ENTITY_TABLES if pg in staged]
    for pg in reversed(entities):
        cur.execute(f'DELETE FROM public."{pg}"')
    for pg in entities:
        written[pg] = _insert_from_staging(cur, pg)

    # 2. Gold snapshot tables: replace only the calculation_date(s) being loaded, keep older history.
    for pg in SNAPSHOT_TABLES:
        if pg in staged:
            cur.execute(
                f'DELETE FROM public."{pg}" WHERE calculation_date IN '
                f'(SELECT DISTINCT calculation_date FROM staging."{pg}")'
            )
            written[pg] = _insert_from_staging(cur, pg)

    # 3. Exceptions log: keep exception_id stable for rows that persist, drop rows that were fixed.
    if "data_quality_exceptions" in staged:
        written["data_quality_exceptions"] = _insert_from_staging(
            cur, "data_quality_exceptions",
            "ON CONFLICT (source_table, record_key, flag_label) DO UPDATE SET description = EXCLUDED.description",
        )
        cur.execute(
            """DELETE FROM public.data_quality_exceptions d
               WHERE NOT EXISTS (
                   SELECT 1 FROM staging.data_quality_exceptions s
                   WHERE s.source_table = d.source_table
                     AND s.record_key = d.record_key
                     AND s.flag_label = d.flag_label)"""
        )

    # 4. Flagged transactions: insert-only. `status` is owned by the application after first load.
    if "flagged_transactions" in staged:
        written["flagged_transactions"] = _insert_from_staging(
            cur, "flagged_transactions", "ON CONFLICT (transaction_id, flag_label) DO NOTHING"
        )

    # 4b. Reconciliation exceptions (specs/multi-source-reconciliation.md): same insert-only
    #     discipline as flagged_transactions - status/resolved_* are owned by the application
    #     after first load, never reset by a rerun.
    if "reconciliation_exceptions" in staged:
        written["reconciliation_exceptions"] = _insert_from_staging(
            cur, "reconciliation_exceptions",
            "ON CONFLICT (source_system, entity_type, entity_id, mismatch_type, field_name) DO NOTHING",
        )

    # 5. FX usage log: the Delta table is the append-only source of truth, so mirror it in full.
    if "fx_rate_usage_log" in staged:
        cur.execute("DELETE FROM public.fx_rate_usage_log")
        written["fx_rate_usage_log"] = _insert_from_staging(cur, "fx_rate_usage_log")

    return written


def connect(host, dbname, user, password, retries=4):
    """Neon suspends idle databases; the first connection can time out while it wakes, so retry."""
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(host=host, dbname=dbname, user=user, password=password,
                                    sslmode="require", connect_timeout=30)
        except psycopg2.OperationalError:
            if attempt == retries:
                raise
            time.sleep(10)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Connection
# MAGIC
# MAGIC Credentials come from the `neon` secret scope (values are redacted in notebook output).
# MAGIC `sslmode=require` is mandatory on Neon; the merge (plain psycopg2, below) sets it explicitly.
# MAGIC The staging write instead uses Databricks' bundled `postgresql` Spark format (not generic
# MAGIC `format("jdbc")`, which this job's serverless compute rejects with
# MAGIC `UNSUPPORTED_DATA_SOURCE_WRITE` - confirmed by an actual failed run, not a guess). That
# MAGIC connector's supported options don't include `sslmode` - Neon requires TLS, but the connector
# MAGIC negotiates it automatically; confirmed by an actual successful run against Neon with no
# MAGIC `sslmode` option passed.

# COMMAND ----------

PG_HOST = dbutils.secrets.get("neon", "host")
PG_DB = dbutils.secrets.get("neon", "database")
PG_USER = dbutils.secrets.get("neon", "user")
PG_PASSWORD = dbutils.secrets.get("neon", "password")

conn = connect(PG_HOST, PG_DB, PG_USER, PG_PASSWORD)
with conn.cursor() as cur:
    cur.execute("CREATE SCHEMA IF NOT EXISTS staging")
    cur.execute("SELECT to_regclass('public.customers')")
    if cur.fetchone()[0] is None:
        raise RuntimeError("public.customers not found — apply db/schema.sql to Neon first (python db/apply_schema.py)")
conn.commit()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Stage each Delta table into Postgres
# MAGIC
# MAGIC Spark's JDBC writer can't write map columns, so they are serialised to JSON text (the merge
# MAGIC casts them to `jsonb`). Snapshot tables keep only their latest `calculation_date` (or the one passed as a parameter).

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import MapType
from pyspark.sql.window import Window

STAGE_JOBS = (
    list(ENTITY_TABLES)
    + [(t, t) for t in SNAPSHOT_TABLES]
    + [("data_quality_exceptions", "data_quality_exceptions"),
       ("flagged_transactions", "flagged_transactions"),
       ("reconciliation_exceptions", "reconciliation_exceptions"),
       ("fx_rate_usage_log", "fx_rate_usage_log")]
)

# Same optional parameter as Notebooks 3, 4 and 6: when set, stage that date's Gold rows rather
# than the newest ones (loading an earlier day after a later one already exists in Delta).
dbutils.widgets.text("calculation_date", "", "Calculation date (YYYY-MM-DD, blank = latest)")
CALCULATION_DATE_PARAM = dbutils.widgets.get("calculation_date").strip() or None

expected_rows = {}

for delta_name, pg_name in STAGE_JOBS:
    if not spark.catalog.tableExists(delta_name):
        print(f"skip {delta_name}: Delta table does not exist")
        continue
    df = spark.table(delta_name)

    for field in df.schema.fields:
        if isinstance(field.dataType, MapType):
            df = df.withColumn(field.name, F.to_json(F.col(field.name)))

    if pg_name in SNAPSHOT_TABLES:
        # The date this run just calculated: the job's `calculation_date` parameter when given (a
        # backfill of an earlier day), otherwise the newest date in the table.
        load_date = CALCULATION_DATE_PARAM or df.agg(F.max("calculation_date")).collect()[0][0]
        df = df.filter(F.col("calculation_date") == load_date)

    if pg_name == "data_quality_exceptions":
        # Records with no key (e.g. a blank-month row) have record_key NULL, but Postgres needs a
        # key for the unique constraint — give each a stable-per-run placeholder, then drop dupes.
        numbering = Window.partitionBy("source_table", "flag_label").orderBy("description")
        df = df.withColumn(
            "record_key",
            F.coalesce(F.col("record_key"), F.concat(F.lit("(no key #"), F.row_number().over(numbering).cast("string"), F.lit(")"))),
        ).dropDuplicates(["source_table", "record_key", "flag_label"])

    expected_rows[pg_name] = df.count()
    (
        df.write.format("postgresql")
        .option("host", PG_HOST).option("port", "5432").option("database", PG_DB)
        .option("dbtable", f"staging.{pg_name}")
        .option("user", PG_USER).option("password", PG_PASSWORD)
        .mode("overwrite")
        .save()
    )
    print(f"staged {pg_name}: {expected_rows[pg_name]} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Merge into `public` (single transaction) and clean up

# COMMAND ----------

try:
    with conn.cursor() as cur:
        written = run_merge(cur)
    conn.commit()
except Exception:
    conn.rollback()
    raise

with conn.cursor() as cur:
    cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
conn.commit()
conn.close()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify
# MAGIC
# MAGIC Rows merged must equal rows staged. `flagged_transactions` and `reconciliation_exceptions`
# MAGIC are exempt: both are insert-only, so rows already in Postgres are deliberately not
# MAGIC re-inserted.

# COMMAND ----------

INSERT_ONLY_TABLES = {"flagged_transactions", "reconciliation_exceptions"}

problems = []
for pg_name, n in expected_rows.items():
    if pg_name in INSERT_ONLY_TABLES:
        print(f"{pg_name}: {written.get(pg_name, 0)} new of {n} staged")
        continue
    ok = written.get(pg_name) == n
    print(f"{'OK  ' if ok else 'FAIL'} {pg_name}: staged {n}, merged {written.get(pg_name)}")
    if not ok:
        problems.append(pg_name)

if problems:
    raise RuntimeError(f"Row-count mismatch after merge: {problems}")
print("Load to Neon complete.")
