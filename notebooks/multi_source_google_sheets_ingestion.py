# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Google Sheets
# MAGIC
# MAGIC Fifth of the 5 free-cloud-source ingestion notebooks from `specs/multi-source-ingestion-adf.md`
# MAGIC (section 9). Stands in for branch/finance ERP data (opex, staffing) — deliberately realistic,
# MAGIC since branch-level cost data at many banks genuinely still lives in a spreadsheet.
# MAGIC **Requires manual setup before this notebook can run**: create a Google Cloud service
# MAGIC account, share the target Sheet with that service account's email (a one-time action outside
# MAGIC any notebook), and put the service-account JSON key in the `multi-source-demo` secret scope
# MAGIC as `google_service_account_json`. None of that has been done yet — this notebook is written
# MAGIC but unrun.
# MAGIC
# MAGIC Input: none (external Sheets API call)
# MAGIC Output: Delta table `bronze_branch_finance`

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (catalog `bank_poc` was created in the UI, since Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG bank_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

import json
import gspread
from google.oauth2.service_account import Credentials
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

dbutils.widgets.text("secret_scope", "multi-source-demo", "Databricks secret scope name")
dbutils.widgets.text("sheet_id", "", "Google Sheet ID (from its URL)")
dbutils.widgets.text("worksheet_name", "Sheet1", "Worksheet/tab name")
dbutils.widgets.text("output_table", "bronze_branch_finance", "Output Delta table name")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
SHEET_ID = dbutils.widgets.get("sheet_id")
WORKSHEET_NAME = dbutils.widgets.get("worksheet_name")
OUTPUT_TABLE = dbutils.widgets.get("output_table")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Authenticate and read
# MAGIC
# MAGIC `gspread.get_all_records()` returns a list of dicts keyed by the sheet's header row — same
# MAGIC "let the source define its own shape" approach as the Mockaroo notebook, no hardcoded schema
# MAGIC here either.

# COMMAND ----------

service_account_json = dbutils.secrets.get(SECRET_SCOPE, "google_service_account_json")
credentials = Credentials.from_service_account_info(json.loads(service_account_json), scopes=SCOPES)
client = gspread.authorize(credentials)

worksheet = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)
records = worksheet.get_all_records()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze

# COMMAND ----------

if records:
    sheets_df = spark.createDataFrame(records).withColumn("ingested_at", F.current_timestamp())
else:
    # An empty sheet still produces a valid, queryable table rather than erroring.
    sheets_df = spark.createDataFrame([], schema="placeholder string").withColumn("ingested_at", F.current_timestamp())

(
    sheets_df.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"{OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count()} rows")
display(spark.table(OUTPUT_TABLE))
