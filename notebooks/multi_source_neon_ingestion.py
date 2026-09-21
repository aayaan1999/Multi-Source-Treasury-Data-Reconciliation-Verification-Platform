# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: Neon (Postgres)
# MAGIC
# MAGIC Third of the 5 free-cloud-source ingestion notebooks from `specs/multi-source-ingestion-adf.md`
# MAGIC (section 9). Stands in for the core banking system's customer/account data.
# MAGIC **Requires manual setup before this notebook can run**: provision a free Neon project,
# MAGIC create `customers`/`accounts` tables with sample rows, and put the JDBC connection string in
# MAGIC the `multi-source-demo` secret scope as `neon_jdbc_url` (with credentials embedded or
# MAGIC supplied separately as `neon_user`/`neon_password`). None of that has been done yet — this
# MAGIC notebook is written but unrun.
# MAGIC
# MAGIC Uses a watermark, not a full-table pull each run, per the pattern already established in
# MAGIC `specs/bidirectional-sync.md`: track the max `updated_at` pulled last time in a small Delta
# MAGIC control table, filter on it this run, then advance it — so a second run only picks up rows
# MAGIC that changed since the first, not the whole table again.
# MAGIC
# MAGIC Input: none (external JDBC read)
# MAGIC Output: Delta table `bronze_neon_customers`; control table `multi_source_watermarks`

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (Default Storage workspaces can't CREATE CATALOG via SQL, so we reuse `workspace`).
spark.sql("USE CATALOG workspace")
spark.sql("CREATE SCHEMA IF NOT EXISTS bank_poc")
spark.sql("USE SCHEMA bank_poc")

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

dbutils.widgets.text("secret_scope", "multi-source-demo", "Databricks secret scope name")
dbutils.widgets.text("source_table", "customers", "Neon source table name")
dbutils.widgets.text("output_table", "bronze_neon_customers", "Output Delta table name")

SECRET_SCOPE = dbutils.widgets.get("secret_scope")
SOURCE_TABLE = dbutils.widgets.get("source_table")
OUTPUT_TABLE = dbutils.widgets.get("output_table")
WATERMARK_SOURCE_KEY = f"neon_{SOURCE_TABLE}"
WATERMARK_TABLE = "multi_source_watermarks"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Watermark read
# MAGIC
# MAGIC Defaults to the epoch if this source has never run before, so the first run pulls
# MAGIC everything and every subsequent run is incremental.

# COMMAND ----------

if spark.catalog.tableExists(WATERMARK_TABLE):
    watermark_row = (
        spark.table(WATERMARK_TABLE)
        .filter(F.col("source_key") == WATERMARK_SOURCE_KEY)
        .orderBy(F.col("last_watermark").desc())
        .limit(1)
        .collect()
    )
    last_watermark = watermark_row[0]["last_watermark"] if watermark_row else "1970-01-01T00:00:00Z"
else:
    last_watermark = "1970-01-01T00:00:00Z"

print(f"Pulling {SOURCE_TABLE} where updated_at > {last_watermark}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## JDBC read

# COMMAND ----------

jdbc_url = dbutils.secrets.get(SECRET_SCOPE, "neon_jdbc_url")
jdbc_user = dbutils.secrets.get(SECRET_SCOPE, "neon_user")
jdbc_password = dbutils.secrets.get(SECRET_SCOPE, "neon_password")

pushdown_query = f"(SELECT * FROM {SOURCE_TABLE} WHERE updated_at > '{last_watermark}') AS watermarked"

neon_df = spark.read.jdbc(
    url=jdbc_url,
    table=pushdown_query,
    properties={"user": jdbc_user, "password": jdbc_password, "driver": "org.postgresql.Driver"},
).withColumn("ingested_at", F.current_timestamp())

new_row_count = neon_df.count()
print(f"Fetched {new_row_count} new/changed rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze (append — this is an incremental pull, not a full snapshot, so each
# MAGIC run's new/changed rows accumulate rather than overwriting prior pulls)

# COMMAND ----------

(
    neon_df.write.format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Advance the watermark
# MAGIC
# MAGIC Only if rows were actually fetched — advancing on a zero-row run is harmless but skipping it
# MAGIC avoids writing a no-op watermark row every single run.

# COMMAND ----------

if new_row_count > 0 and "updated_at" in neon_df.columns:
    new_watermark = neon_df.agg(F.max("updated_at").alias("v")).collect()[0]["v"]
    watermark_row_df = spark.createDataFrame(
        [(WATERMARK_SOURCE_KEY, str(new_watermark))], schema=["source_key", "last_watermark"]
    ).withColumn("recorded_at", F.current_timestamp())

    (
        watermark_row_df.write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(WATERMARK_TABLE)
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"{OUTPUT_TABLE} total rows: {spark.table(OUTPUT_TABLE).count() if spark.catalog.tableExists(OUTPUT_TABLE) else 0}")
