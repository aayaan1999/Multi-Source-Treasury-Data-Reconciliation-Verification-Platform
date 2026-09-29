# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Salesforce
# MAGIC
# MAGIC Reads Salesforce Accounts into Bronze. Stands in for the CRM (`specs/multi-source-ingestion-adf.md`
# MAGIC section 9); connected from the app's Data ingestion tab (`specs/screen-data-ingestion.md`).
# MAGIC
# MAGIC **Sign-in: OAuth 2.0 client credentials** against the org's own My Domain address, with the
# MAGIC Consumer Key and Secret of a Salesforce **External Client App** whose "Run As" user sets what it can
# MAGIC read. This replaced the username-password flow on 2026-09-29: Salesforce stopped allowing new
# MAGIC Connected Apps in Spring '26, and External Client Apps don't support the username-password flow.
# MAGIC
# MAGIC **Settings** come from the Databricks secret scope `bank-data-sources`, where the app's
# MAGIC Connect & Save puts them: `salesforce-instance_url`, `salesforce-client_id`,
# MAGIC `salesforce-client_secret`. When Salesforce isn't connected the notebook stops cleanly with
# MAGIC "skipped"; when sign-in or the query fails it records the failure and stops with "failed: ...".
# MAGIC Either way the rest of the pipeline run is unaffected.
# MAGIC
# MAGIC Input: none (Salesforce REST API)
# MAGIC Output: Delta table `bronze_salesforce_accounts`; one row per run in Neon `ingestion_runs`
# MAGIC (shown under "Recent ingestions" on the Data ingestion tab); task value `status`
# MAGIC (loaded / skipped / failed), which the `salesforce_reconciliation` task checks before comparing.

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
dbutils.widgets.text("output_table", "bronze_salesforce_accounts", "Output Delta table name")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
OUTPUT_TABLE = dbutils.widgets.get("output_table")
SOURCE_KEY = "salesforce"                       # the app's source key (backend/app/connectors.py)
SOQL_QUERY = "SELECT Id, AccountNumber, Name, Industry, BillingCountry, CreatedDate FROM Account"
API_VERSION = "v60.0"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recording the run in Neon
# MAGIC
# MAGIC One `ingestion_runs` row per run (success or failure) so the app can show it. Uses the same
# MAGIC `neon` secret scope as `load_to_postgres.py`. A failure to record never hides the real outcome.

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
                (SOURCE_KEY, "Account", status, rows, message[:500], json.dumps(run_context())),
            )
        conn.close()
    except Exception as e:                       # the Delta write already happened (or the real error is raised below)
        print(f"Couldn't record the run in Neon: {type(e).__name__}")


def run_context():
    try:
        tags = json.loads(dbutils.notebook.entry_point.getDbutils().notebook().getContext().safeToJson())["attributes"]
        return {"job_id": tags.get("jobId"), "run_id": tags.get("multitaskParentRunId") or tags.get("currentRunId")}
    except Exception:
        return {}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Is Salesforce connected?
# MAGIC
# MAGIC The three settings exist only once someone has connected Salesforce in the app. Without them the
# MAGIC notebook ends here, successfully, so "Run all sources now" still loads everything else.

# COMMAND ----------

def setting(key):
    try:
        return dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_KEY}-{key}")
    except Exception:
        return None

INSTANCE_URL, CLIENT_ID, CLIENT_SECRET = setting("instance_url"), setting("client_id"), setting("client_secret")
if not (INSTANCE_URL and CLIENT_ID and CLIENT_SECRET):
    dbutils.jobs.taskValues.set(key="status", value="skipped")
    dbutils.notebook.exit("skipped: Salesforce is not connected in the app")
INSTANCE_URL = INSTANCE_URL.rstrip("/")

# COMMAND ----------

# MAGIC %md
# MAGIC ## OAuth 2.0 client credentials
# MAGIC
# MAGIC Must go to the org's My Domain address - Salesforce rejects this flow on login.salesforce.com.
# MAGIC Retries once on a network error; a 4xx (wrong key or secret, flow not enabled) fails at once
# MAGIC with Salesforce's own error code, never the secret.

# COMMAND ----------

def get_token():
    for attempt in (1, 2):
        try:
            response = requests.post(
                f"{INSTANCE_URL}/services/oauth2/token",
                data={"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                timeout=30,
            )
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"Couldn't reach Salesforce at {INSTANCE_URL}: {type(e).__name__}")
            time.sleep(5)
            continue
        if response.status_code != 200:
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise RuntimeError(f"Salesforce refused the sign-in ({response.status_code}): "
                               f"{body.get('error', '')} {body.get('error_description', '')}".strip())
        return response.json()

# A Salesforce problem is recorded (the Data ingestion tab shows it as Failed) and ends this task without
# failing the whole pipeline run: the core banking load that runs alongside it is still valid.
try:
    auth = get_token()
except Exception as e:
    record_run("failed", 0, str(e))
    dbutils.jobs.taskValues.set(key="status", value="failed")
    dbutils.notebook.exit(f"failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Query Account via REST
# MAGIC
# MAGIC Follows `nextRecordsUrl` so every page is read, not just the first 2,000 rows.

# COMMAND ----------

headers = {"Authorization": f"Bearer {auth['access_token']}"}
records = []
try:
    response = requests.get(f"{auth['instance_url']}/services/data/{API_VERSION}/query", headers=headers,
                            params={"q": SOQL_QUERY}, timeout=60)
    while True:
        response.raise_for_status()
        page = response.json()
        records.extend(page.get("records", []))
        if page.get("done", True):
            break
        response = requests.get(f"{auth['instance_url']}{page['nextRecordsUrl']}", headers=headers, timeout=60)
except Exception as e:
    record_run("failed", 0, f"Account query failed: {e}")
    dbutils.jobs.taskValues.set(key="status", value="failed")
    dbutils.notebook.exit(f"failed: Account query failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze
# MAGIC
# MAGIC Explicit schema, so a column that is empty on every record (e.g. no Industry filled in) still
# MAGIC gets its type instead of breaking schema inference. Tagged with its source like every other
# MAGIC Bronze record (`specs/source-tagging.md`).

# COMMAND ----------

# AccountNumber carries the bank's customer_id - the key the CRM reconciliation matches on
# (multi_source_reconciliation.py with source=salesforce).
SCHEMA = "Id string, AccountNumber string, Name string, Industry string, BillingCountry string, CreatedDate string"
rows = [{k: r.get(k) for k in ("Id", "AccountNumber", "Name", "Industry", "BillingCountry", "CreatedDate")} for r in records]

salesforce_df = (
    spark.createDataFrame(rows, schema=SCHEMA)
    .withColumn("source_system", F.lit("SALESFORCE"))
    .withColumn("ingested_at", F.current_timestamp())
)

(
    salesforce_df.write.format("delta")
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
record_run("success", count, f"{count} Accounts loaded into {OUTPUT_TABLE}")
dbutils.jobs.taskValues.set(key="status", value="loaded")      # read by the salesforce_reconciliation task
dbutils.notebook.exit(f"loaded: {count} Accounts")
