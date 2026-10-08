# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Core Banking (PostgreSQL)
# MAGIC
# MAGIC Reads the core banking system's `customers` and `accounts` tables from a PostgreSQL database into
# MAGIC Bronze, for the core-system reconciliation (`multi_source_reconciliation.py` with `source=neon`).
# MAGIC Connected from the app's Data ingestion tab (`specs/screen-data-ingestion.md`), the same way as
# MAGIC Salesforce. In the demo the database is a second Neon project, never the app's own database.
# MAGIC
# MAGIC **Settings** come from the Databricks secret scope `bank-data-sources`, where the app's Connect &
# MAGIC Save puts them: `postgresql-host`, `postgresql-port`, `postgresql-database`, `postgresql-username`,
# MAGIC `postgresql-password`. When PostgreSQL isn't connected the notebook stops cleanly with "skipped";
# MAGIC when sign-in or a read fails it records the failure and stops with "failed: ...". Either way the
# MAGIC rest of the pipeline run is unaffected. (Until 2026-10-08 this notebook read a hand-made
# MAGIC `multi-source-demo` scope instead; that scope is no longer used.)
# MAGIC
# MAGIC **A full snapshot every run, not an incremental pull.** The earlier version appended only rows whose
# MAGIC `updated_at` had moved past a watermark. That needed an `updated_at` column the bank's tables may not
# MAGIC have, never noticed a deleted row, and kept the old database's watermark when a different database
# MAGIC was connected. Reconciliation compares against the system's current state, so each run replaces
# MAGIC the Bronze tables with what the database holds now.
# MAGIC
# MAGIC Input: PostgreSQL tables `customers` (customer_id, name, segment, risk_rating, branch_id) and
# MAGIC `accounts` (account_id, customer_id, type, currency, balance) - other columns are ignored
# MAGIC Output: Delta tables `bronze_neon_customers`, `bronze_neon_accounts`; one row per table per run in
# MAGIC Neon `ingestion_runs` (shown under "Recent ingestions"); task value `status` (loaded / skipped /
# MAGIC failed), which the `core_banking_reconciliation` task checks before comparing.

# COMMAND ----------

# MAGIC %pip install psycopg2-binary

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

import json

import psycopg2
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC The Bronze table names keep their `neon` prefix: the reconciliation notebook, `load_to_postgres.py`
# MAGIC and the app's Reconciliation screen all know core banking as source `neon`.

# COMMAND ----------

dbutils.widgets.text("secret_scope", "bank-data-sources", "Databricks secret scope the app writes connector settings to")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
SOURCE_KEY = "postgresql"                       # the app's source key (backend/app/connectors.py)
# source table -> (Bronze table, columns read). The same columns the app's Test connection checks.
TABLES = {
    "customers": ("bronze_neon_customers", ["customer_id", "name", "segment", "risk_rating", "branch_id"]),
    "accounts": ("bronze_neon_accounts", ["account_id", "customer_id", "type", "currency", "balance"]),
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recording the run in Neon
# MAGIC
# MAGIC One `ingestion_runs` row per table per run (success or failure) so the app can show it. Uses the
# MAGIC app database's `neon` secret scope, like `load_to_postgres.py`. A failure to record never hides
# MAGIC the real outcome.

# COMMAND ----------

def record_run(data_name, status, rows, message):
    try:
        conn = psycopg2.connect(host=dbutils.secrets.get("neon", "host"), dbname=dbutils.secrets.get("neon", "database"),
                                user=dbutils.secrets.get("neon", "user"), password=dbutils.secrets.get("neon", "password"),
                                sslmode="require", connect_timeout=30)
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingestion_runs (source_key, data_name, status, rows_received, message, databricks_run)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (SOURCE_KEY, data_name, status, rows, message[:500], json.dumps(run_context())),
            )
        conn.close()
    except Exception as e:                       # the Delta write already happened (or the real error is reported below)
        print(f"Couldn't record the run in Neon: {type(e).__name__}")


def run_context():
    try:
        tags = json.loads(dbutils.notebook.entry_point.getDbutils().notebook().getContext().safeToJson())["attributes"]
        return {"job_id": tags.get("jobId"), "run_id": tags.get("multitaskParentRunId") or tags.get("currentRunId")}
    except Exception:
        return {}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Is PostgreSQL connected?
# MAGIC
# MAGIC The settings exist only once someone has connected PostgreSQL in the app. Without them the
# MAGIC notebook ends here, successfully, so "Run all sources now" still loads everything else.

# COMMAND ----------

def setting(key):
    try:
        return dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_KEY}-{key}")
    except Exception:
        return None

HOST, PORT, DATABASE, USERNAME, PASSWORD = (setting(k) for k in ("host", "port", "database", "username", "password"))
if not (HOST and DATABASE and USERNAME and PASSWORD):
    dbutils.jobs.taskValues.set(key="status", value="skipped")
    dbutils.notebook.exit("skipped: PostgreSQL is not connected in the app")
PORT = PORT or "5432"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read both tables
# MAGIC
# MAGIC Databricks' bundled `postgresql` format, not generic `format("jdbc")`: this job runs on serverless
# MAGIC compute, which rejects the generic JDBC source (`specs/pipeline-job-and-neon-load.md`). Selecting
# MAGIC the named columns pushes the column list down to the database and turns a missing column into a
# MAGIC clear error. Both tables are read before either is written, so a failure on `accounts` never
# MAGIC leaves Bronze holding today's customers next to yesterday's accounts.

# COMMAND ----------

def read_table(name, columns):
    return (
        spark.read.format("postgresql")
        .option("host", HOST).option("port", PORT).option("database", DATABASE)
        .option("dbtable", name)
        .option("user", USERNAME).option("password", PASSWORD)
        .load()
        .select(*columns)
        .withColumn("source_system", F.lit("CORE_POSTGRES"))
        .withColumn("ingested_at", F.current_timestamp())
    )

frames = {}
for name, (_, columns) in TABLES.items():
    try:
        # No .cache(): serverless compute refuses it (NOT_SUPPORTED_WITH_SERVERLESS, found on the first live run).
        # count() still forces the read, so sign-in and missing-column errors surface here, before any write;
        # the write below reads the table again, which costs little at core banking's size.
        df = read_table(name, columns)
        frames[name] = (df, df.count())
    except Exception as e:
        # First line only: Spark's error text can run to pages, and never contains the password.
        reason = f"Couldn't read {name} from {HOST}/{DATABASE}: {str(e).strip().splitlines()[0][:300]}"
        record_run(name, "failed", 0, reason)
        dbutils.jobs.taskValues.set(key="status", value="failed")
        dbutils.notebook.exit(f"failed: {reason}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze (replace)

# COMMAND ----------

for name, (df, count) in frames.items():
    output_table = TABLES[name][0]
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(output_table)
    )
    print(f"{output_table}: {count} rows")
    record_run(name, "success", count, f"{count} {name} loaded into {output_table}")

dbutils.jobs.taskValues.set(key="status", value="loaded")       # read by the core_banking_reconciliation task
dbutils.notebook.exit("loaded: " + ", ".join(f"{count} {name}" for name, (_, count) in frames.items()))
