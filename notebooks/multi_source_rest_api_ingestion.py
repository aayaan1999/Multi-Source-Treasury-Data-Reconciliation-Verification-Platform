# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Loan Origination System (REST API)
# MAGIC
# MAGIC Reads the loan origination system's loans from a JSON REST API into Bronze, for the loan
# MAGIC reconciliation (`multi_source_reconciliation.py` with `source=los`). Connected from the app's Data
# MAGIC ingestion tab as **REST API** (`specs/screen-data-ingestion.md` section 3d). In the demo the API is a
# MAGIC Supabase project's auto-generated REST API over a `loans` table (`scripts/seed_loans_api.py`).
# MAGIC
# MAGIC **Settings** come from the Databricks secret scope `bank-data-sources`, where the app's Connect &
# MAGIC Save puts them: `rest_api-base_url`, `rest_api-endpoint`, and optionally `rest_api-auth_header` /
# MAGIC `rest_api-api_key` (for Supabase: header `apikey` and the project's publishable key). When the REST
# MAGIC API isn't connected the notebook stops cleanly with "skipped"; when the call fails it records the
# MAGIC failure and stops with "failed: ...". Either way the rest of the pipeline run is unaffected.
# MAGIC
# MAGIC **The API must return a JSON array of loans** (or an object holding one under `data`, `items`,
# MAGIC `records` or `results`), each with at least `LOAN_COLUMNS` below. Pages are read with `limit` /
# MAGIC `offset` query parameters, which Supabase (PostgREST) understands; an API that ignores them sends
# MAGIC everything in one page, and the loop notices and stops. A full snapshot every run.
# MAGIC
# MAGIC Input: none (external REST call)
# MAGIC Output: Delta table `bronze_los_loans`; one row per run in Neon `ingestion_runs`; task value `status`
# MAGIC (loaded / skipped / failed), which the `loans_api_reconciliation` task checks before comparing.

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
import time

import psycopg2
import requests
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

dbutils.widgets.text("secret_scope", "bank-data-sources", "Databricks secret scope the app writes connector settings to")
dbutils.widgets.text("output_table", "bronze_los_loans", "Output Delta table name")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
OUTPUT_TABLE = dbutils.widgets.get("output_table")
SOURCE_KEY = "rest_api"                         # the app's source key (backend/app/connectors.py)
# What the loan reconciliation compares; the same list the app's Test connection checks (connectors.LOAN_COLUMNS).
TEXT_COLUMNS = ["loan_id", "customer_id", "product", "currency"]
NUMBER_COLUMNS = ["principal", "outstanding", "interest_rate"]
LOAN_COLUMNS = TEXT_COLUMNS + NUMBER_COLUMNS
PAGE_SIZE = 1000                                 # Supabase's default maximum rows per response
MAX_PAGES = 1000                                 # a runaway guard: a million loans

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recording the run in Neon
# MAGIC
# MAGIC One `ingestion_runs` row per run (success or failure) so the app can show it. Uses the app
# MAGIC database's `neon` secret scope, like `load_to_postgres.py`. A failure to record never hides the
# MAGIC real outcome.

# COMMAND ----------

def record_run(status, rows, message):
    try:
        conn = psycopg2.connect(host=dbutils.secrets.get("neon", "host"), dbname=dbutils.secrets.get("neon", "database"),
                                user=dbutils.secrets.get("neon", "user"), password=dbutils.secrets.get("neon", "password"),
                                sslmode="require", connect_timeout=30)
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingestion_runs (source_key, data_name, status, rows_received, message, databricks_run)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (SOURCE_KEY, "loans", status, rows, message[:500], json.dumps(run_context())),
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


def fail(reason):
    record_run("failed", 0, reason)
    dbutils.jobs.taskValues.set(key="status", value="failed")
    dbutils.notebook.exit(f"failed: {reason}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Is the REST API connected?

# COMMAND ----------

def setting(key):
    try:
        return dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_KEY}-{key}")
    except Exception:
        return None

BASE_URL, ENDPOINT, AUTH_HEADER, API_KEY = (setting(k) for k in ("base_url", "endpoint", "auth_header", "api_key"))
if not (BASE_URL and ENDPOINT):
    dbutils.jobs.taskValues.set(key="status", value="skipped")
    dbutils.notebook.exit("skipped: the REST API is not connected in the app")

URL = BASE_URL.rstrip("/") + "/" + ENDPOINT.lstrip("/")
HEADERS = {"Accept": "application/json"}
if AUTH_HEADER and API_KEY:
    HEADERS[AUTH_HEADER] = API_KEY

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read every page
# MAGIC
# MAGIC One retry on a network error. Any answer other than 200 or 206 (a page of a larger result) fails at once with the API's own status and the
# MAGIC start of its message (never the key). Stops on an empty or short page, or when a page starts with
# MAGIC the same record as the previous one (the API ignores `offset`, so it already sent everything).

# COMMAND ----------

def get_page(offset):
    for attempt in (1, 2):
        try:
            response = requests.get(URL, headers=HEADERS, params={"limit": PAGE_SIZE, "offset": offset}, timeout=60)
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"Couldn't reach {URL}: {type(e).__name__}")
            time.sleep(5)
            continue
        if response.status_code not in (200, 206):     # 206: a page of a larger result (PostgREST)
            raise RuntimeError(f"The API answered {response.status_code} at {URL}: {response.text.strip()[:200]}")
        body = response.json()
        if isinstance(body, dict):
            body = next((body[k] for k in ("data", "items", "records", "results") if isinstance(body.get(k), list)), body)
        if not isinstance(body, list):
            raise RuntimeError(f"The API at {URL} didn't return a list of loans")
        return body

records = []
try:
    previous_first = None
    for page_number in range(MAX_PAGES):
        page = get_page(page_number * PAGE_SIZE)
        if not page or (previous_first is not None and page[0] == previous_first):
            break
        records.extend(page)
        if len(page) < PAGE_SIZE:
            break
        previous_first = page[0]
except Exception as e:
    fail(str(e))

# No loans at all is a setup problem (wrong endpoint, a filter, row security), not a loan system that lost
# every loan: comparing it would turn each of our loans into a "missing" task.
if not records:
    fail(f"The API at {URL} returned no loans")
missing = [c for c in LOAN_COLUMNS if c not in records[0]]
if missing:
    fail(f"The loans from {URL} have no {', '.join(missing)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze (replace)
# MAGIC
# MAGIC Explicit schema: text columns as strings, amounts and the rate as doubles. A number the API sends
# MAGIC as text ("800000.00") is converted; one that isn't a number becomes null, and the reconciliation then
# MAGIC shows it as a difference rather than the run failing. Tagged with its source like every other Bronze
# MAGIC record (`specs/source-tagging.md`).

# COMMAND ----------

def as_number(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

def as_text(value):
    return None if value is None else str(value).strip()

SCHEMA = ", ".join([f"{c} string" for c in TEXT_COLUMNS] + [f"{c} double" for c in NUMBER_COLUMNS])
rows = [tuple([as_text(r.get(c)) for c in TEXT_COLUMNS] + [as_number(r.get(c)) for c in NUMBER_COLUMNS]) for r in records]

loans_df = (
    spark.createDataFrame(rows, schema=SCHEMA)
    .withColumn("source_system", F.lit("LOS_API"))
    .withColumn("ingested_at", F.current_timestamp())
)

(
    loans_df.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks and run record

# COMMAND ----------

count = spark.table(OUTPUT_TABLE).count()
print(f"{OUTPUT_TABLE}: {count} rows")
record_run("success", count, f"{count} loans loaded into {OUTPUT_TABLE}")
dbutils.jobs.taskValues.set(key="status", value="loaded")      # read by the loans_api_reconciliation task
dbutils.notebook.exit(f"loaded: {count} loans")
