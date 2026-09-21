# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Salesforce Developer Edition
# MAGIC
# MAGIC Fourth of the 5 free-cloud-source ingestion notebooks from `specs/multi-source-ingestion-adf.md`
# MAGIC (section 9). Stands in for the CRM. **Requires manual setup before this notebook can run**:
# MAGIC sign up for a free Salesforce Developer org, register a Connected App to get an OAuth client
# MAGIC ID/secret, and put `sf_client_id`, `sf_client_secret`, `sf_username`, `sf_password`,
# MAGIC `sf_security_token` in the `multi-source-demo` secret scope. None of that has been done yet
# MAGIC — this notebook is written but unrun. The most involved of the five sources, due to the
# MAGIC OAuth flow.
# MAGIC
# MAGIC Input: none (external REST call via OAuth)
# MAGIC Output: Delta table `bronze_salesforce_accounts`

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

import requests
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

dbutils.widgets.text("secret_scope", "multi-source-demo", "Databricks secret scope name")
dbutils.widgets.text("login_url", "https://login.salesforce.com", "Salesforce login base URL")
dbutils.widgets.text("output_table", "bronze_salesforce_accounts", "Output Delta table name")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
LOGIN_URL = dbutils.widgets.get("login_url")
OUTPUT_TABLE = dbutils.widgets.get("output_table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## OAuth2 token exchange
# MAGIC
# MAGIC Uses the username-password OAuth flow (`grant_type=password`), the simplest flow for a
# MAGIC server-side batch job with no interactive user present — appropriate for a Developer Edition
# MAGIC demo org, not what a production integration would use (that would be a JWT bearer or
# MAGIC client-credentials flow with a dedicated integration user).

# COMMAND ----------

client_id = dbutils.secrets.get(SECRET_SCOPE, "sf_client_id")
client_secret = dbutils.secrets.get(SECRET_SCOPE, "sf_client_secret")
username = dbutils.secrets.get(SECRET_SCOPE, "sf_username")
password = dbutils.secrets.get(SECRET_SCOPE, "sf_password")
security_token = dbutils.secrets.get(SECRET_SCOPE, "sf_security_token")

token_response = requests.post(
    f"{LOGIN_URL}/services/oauth2/token",
    data={
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": f"{password}{security_token}",
    },
    timeout=30,
)
token_response.raise_for_status()
auth = token_response.json()
access_token = auth["access_token"]
instance_url = auth["instance_url"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Query Account + Contact via REST
# MAGIC
# MAGIC Plain SOQL query through the REST API — fine at Developer Edition's sample-data volume;
# MAGIC the Bulk API (mentioned in the spec) would only matter at a scale this demo doesn't reach.

# COMMAND ----------

SOQL_QUERY = "SELECT Id, Name, Industry, BillingCountry, CreatedDate FROM Account"

query_response = requests.get(
    f"{instance_url}/services/data/v60.0/query",
    headers={"Authorization": f"Bearer {access_token}"},
    params={"q": SOQL_QUERY},
    timeout=30,
)
query_response.raise_for_status()
records = query_response.json().get("records", [])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze

# COMMAND ----------

cleaned_records = [
    {k: v for k, v in r.items() if k != "attributes"}
    for r in records
]

if cleaned_records:
    salesforce_df = spark.createDataFrame(cleaned_records).withColumn("ingested_at", F.current_timestamp())
else:
    # Empty result still produces a valid, queryable table rather than erroring on createDataFrame([]).
    salesforce_df = spark.createDataFrame([], schema="Id string, Name string, Industry string, BillingCountry string, CreatedDate string") \
        .withColumn("ingested_at", F.current_timestamp())

(
    salesforce_df.write.format("delta")
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
