# Databricks notebook source
# MAGIC %md
# MAGIC # Notebook 4: Exception Summary Report
# MAGIC
# MAGIC Summarises Notebook 2's `data_quality_exceptions` log into two small demo-ready tables, per
# MAGIC `specs/notebook-04-exception-summary.md`. Simplest notebook in the pipeline — counting rows
# MAGIC needs no currency conversion, so there's no FX dependency here at all.
# MAGIC
# MAGIC Input: `data_quality_exceptions`, and the 8 `raw_*` tables (row-count denominator only)
# MAGIC Output: Delta tables `exception_summary_by_flag`, `exception_summary_by_table`

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

SOURCE_TABLES = [
    "customers", "accounts", "loans", "transactions",
    "branches", "capital_positions", "liquidity_daily", "fx_rates",
]
CALCULATION_DATE = F.current_date()

# COMMAND ----------

data_quality_exceptions = spark.table("data_quality_exceptions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## `exception_summary_by_flag`
# MAGIC
# MAGIC One row per `(source_table, flag_label)` that occurs at least once — a plain grouped count,
# MAGIC no zero-fill needed here since an absent combination legitimately means zero.

# COMMAND ----------

exception_summary_by_flag = (
    data_quality_exceptions
    .groupBy("source_table", "flag_label")
    .agg(F.count("*").alias("exception_count"))
    .withColumn("calculation_date", CALCULATION_DATE)
    .select("calculation_date", "source_table", "flag_label", "exception_count")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `exception_summary_by_table`
# MAGIC
# MAGIC `LEFT JOIN` from the fixed 8-table list against the exceptions log, not an inner join — a
# MAGIC table with zero exceptions must still show `flagged_record_count = 0`, not disappear from
# MAGIC the output (spec section 4). `flagged_record_count` counts `DISTINCT record_key` so a
# MAGIC record carrying multiple flags isn't counted as two bad records.

# COMMAND ----------

raw_row_counts = spark.createDataFrame(
    [(t, spark.table(f"raw_{t}").count()) for t in SOURCE_TABLES],
    schema=["source_table", "raw_row_count"],
)

flagged_counts = (
    data_quality_exceptions
    .groupBy("source_table")
    .agg(F.countDistinct("record_key").alias("flagged_record_count"))
)

exception_summary_by_table = (
    raw_row_counts
    .join(flagged_counts, on="source_table", how="left")
    .withColumn("flagged_record_count", F.coalesce(F.col("flagged_record_count"), F.lit(0)))
    .withColumn("exception_rate_pct", F.col("flagged_record_count") / F.col("raw_row_count") * 100)
    .withColumn("calculation_date", CALCULATION_DATE)
    .select("calculation_date", "source_table", "raw_row_count", "flagged_record_count", "exception_rate_pct")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write outputs (idempotent per-day overwrite, same pattern as Notebook 3)

# COMMAND ----------

def overwrite_today(df, table_name: str):
    if spark.catalog.tableExists(table_name):
        existing = spark.table(table_name).filter(F.col("calculation_date") != CALCULATION_DATE)
        df = existing.unionByName(df)
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table_name)
    )


overwrite_today(exception_summary_by_flag, "exception_summary_by_flag")
overwrite_today(exception_summary_by_table, "exception_summary_by_table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"exception_summary_by_table: {spark.table('exception_summary_by_table').filter(F.col('calculation_date') == CALCULATION_DATE).count()} rows (expect 8)")
display(spark.table("exception_summary_by_table").filter(F.col("calculation_date") == CALCULATION_DATE).orderBy(F.col("exception_rate_pct").desc()))
display(spark.table("exception_summary_by_flag").filter(F.col("calculation_date") == CALCULATION_DATE).orderBy("source_table", "flag_label"))
