# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Mockaroo
# MAGIC
# MAGIC Second of the 5 free-cloud-source ingestion notebooks from `specs/multi-source-ingestion-adf.md`
# MAGIC (section 9). Stands in for a Loan Origination System. **Requires manual setup before this
# MAGIC notebook can run**: design a loan-origination schema in Mockaroo's UI
# MAGIC (`loan_id`, `customer_id`, `amount`, `product`, `origination_date`, ...), generate a mock
# MAGIC REST endpoint, and put its API key in the `multi-source-demo` secret scope as
# MAGIC `mockaroo_api_key`. None of that has been done yet — this notebook is written but unrun.
# MAGIC
# MAGIC Input: none (external REST call)
# MAGIC Output: Delta table `bronze_mockaroo_loans`

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (Default Storage workspaces can't CREATE CATALOG via SQL, so we reuse `workspace`).
spark.sql("USE CATALOG workspace")
spark.sql("CREATE SCHEMA IF NOT EXISTS bank_poc")
spark.sql("USE SCHEMA bank_poc")

# COMMAND ----------

import requests
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

dbutils.widgets.text("mockaroo_endpoint", "https://my.api.mockaroo.com/loan_originations.json", "Mockaroo mock API URL")
dbutils.widgets.text("secret_scope", "multi-source-demo", "Databricks secret scope name")
dbutils.widgets.text("output_table", "bronze_mockaroo_loans", "Output Delta table name")

MOCKAROO_ENDPOINT = dbutils.widgets.get("mockaroo_endpoint")
SECRET_SCOPE = dbutils.widgets.get("secret_scope")
OUTPUT_TABLE = dbutils.widgets.get("output_table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch
# MAGIC
# MAGIC Mockaroo's mock API returns a JSON array shaped by whatever schema was designed in its UI —
# MAGIC this notebook doesn't assume specific field names, it just lands whatever comes back.
# MAGIC `spark.read.json` on the raw response, not a hand-built schema, so a schema change made in
# MAGIC Mockaroo's UI doesn't require a code change here.

# COMMAND ----------

api_key = dbutils.secrets.get(SECRET_SCOPE, "mockaroo_api_key")
response = requests.get(MOCKAROO_ENDPOINT, headers={"X-API-Key": api_key}, timeout=30)
response.raise_for_status()
raw_json = response.text

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze
# MAGIC
# MAGIC `spark.read.json` needs an RDD/path, not an in-memory string directly — writing the raw
# MAGIC response to a temp path first is the standard workaround for parsing an API response with
# MAGIC Spark's JSON reader rather than pandas.

# COMMAND ----------

temp_path = "/tmp/mockaroo_raw_response.json"
dbutils.fs.put(temp_path, raw_json, overwrite=True)

mockaroo_df = spark.read.json(temp_path).withColumn("ingested_at", F.current_timestamp())

(
    mockaroo_df.write.format("delta")
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
