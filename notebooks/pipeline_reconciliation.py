# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Pipeline Reconciliation per Source (FLOW-3)
# MAGIC
# MAGIC Per `specs/pipeline-reconciliation.md`. For every run + source + country + table, compares what
# MAGIC the source **sent** (`raw_*`, Notebook 1) with what **survived cleaning** (`*_clean`, Notebook 2):
# MAGIC row counts, and for money tables the amount per currency. A gap — rows rejected, or an amount
# MAGIC that changed — becomes an `OPEN` item for the Reconciliation tab, so nothing is lost silently.
# MAGIC
# MAGIC **Different from `multi_source_reconciliation.py`.** That one asks "does our copy match the
# MAGIC bank's core system?"; this one asks "did our own pipeline lose anything?".
# MAGIC
# MAGIC Relies on Notebook 1's source tags (`specs/source-tagging.md`): `ingest_batch_id`,
# MAGIC `source_system`, `source_country` on every raw and clean row.
# MAGIC
# MAGIC Input: `raw_*` and `*_clean` for the 8 source tables
# MAGIC Output: Delta table `pipeline_reconciliation` (insert-only merge, like `flagged_transactions`)

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

from delta.tables import DeltaTable
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC Money tables are compared by amount **per currency** as well as by row count — adding USD to
# MAGIC LBP would mean nothing. The other tables are compared by row count only.

# COMMAND ----------

SOURCE_TABLES = [
    "branches", "customers", "accounts", "loans", "transactions",
    "capital_positions", "liquidity_daily", "fx_rates",
]

# table -> (amount column, currency column). Which amounts matter is an open question for the bank
# (spec section 8); these are the money columns each table has today.
AMOUNT_COLUMNS = {
    "transactions": ("amount", "currency"),
    "accounts": ("balance", "currency"),
    "loans": ("outstanding", "currency"),
}

# One item per delivery: which run, which source, which country.
ITEM_KEYS = ["ingest_batch_id", "source_system", "source_country"]

# Differences smaller than this are float noise from summing, not a real gap.
AMOUNT_TOLERANCE = 0.005

AMOUNTS_TYPE = "map<string,struct<received:double,clean:double,gap:double>>"

# COMMAND ----------

# Fail early with a clear message if Notebook 1 predates source tagging: without the tags there is
# nothing to group by, and a silent empty result would look like "every source reconciled".
for table in SOURCE_TABLES:
    missing = [c for c in ITEM_KEYS if c not in spark.table(f"raw_{table}").columns]
    if missing:
        raise RuntimeError(f"raw_{table} has no {missing}: run the updated Notebook 1 (specs/source-tagging.md) first")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compare one table
# MAGIC
# MAGIC Row counts per item, received vs kept. For money tables, amounts summed per currency on both
# MAGIC sides and collected into one `amounts_by_currency` map per item. A missing or blank currency
# MAGIC is labelled `UNKNOWN` so a rejected row with a broken currency still shows up as its own line.

# COMMAND ----------

def currency_label(col_name: str):
    return F.when(F.trim(F.coalesce(F.col(col_name), F.lit(""))) == "", F.lit("UNKNOWN")).otherwise(F.col(col_name))


def reconcile_table(table: str) -> DataFrame:
    raw = spark.table(f"raw_{table}")
    clean = spark.table(f"{table}_clean")
    amount_col, currency_col = AMOUNT_COLUMNS.get(table, (None, None))

    # Rows received per item, and (money tables) how many of them had no readable amount — those
    # count as rows but add nothing to the amount, so the popup says how many there were.
    unreadable = (
        F.sum(F.when(F.col(amount_col).isNull(), 1).otherwise(0)) if amount_col else F.lit(0)
    ).cast("long").alias("unreadable_amount_rows")
    received = raw.groupBy(*ITEM_KEYS).agg(F.count("*").alias("received_rows"), unreadable)
    kept = clean.groupBy(*ITEM_KEYS).agg(F.count("*").alias("clean_rows"))

    # Left join from received: clean rows are a subset of the same run's raw rows, so every kept
    # item has a received item; a source whose rows were all rejected keeps clean_rows = 0.
    items = received.join(kept, ITEM_KEYS, "left").fillna(0, ["clean_rows"])

    if amount_col:
        received_amounts = raw.groupBy(*ITEM_KEYS, currency_label(currency_col).alias("currency")).agg(
            F.coalesce(F.sum(amount_col), F.lit(0.0)).alias("received")
        )
        kept_amounts = clean.groupBy(*ITEM_KEYS, currency_label(currency_col).alias("currency")).agg(
            F.coalesce(F.sum(amount_col), F.lit(0.0)).alias("clean")
        )
        # gap = received - kept, signed: dropping a negative balance makes the kept total larger.
        per_currency = (
            received_amounts.join(kept_amounts, ITEM_KEYS + ["currency"], "left")
            .fillna(0.0, ["clean"])
            .withColumn("gap", F.round(F.col("received") - F.col("clean"), 4))
        )
        amounts = per_currency.groupBy(*ITEM_KEYS).agg(
            F.map_from_entries(
                F.collect_list(
                    F.struct(
                        F.col("currency"),
                        F.struct(
                            F.round("received", 4).alias("received"),
                            F.round("clean", 4).alias("clean"),
                            F.col("gap"),
                        ),
                    )
                )
            ).cast(AMOUNTS_TYPE).alias("amounts_by_currency")
        )
        items = items.join(amounts, ITEM_KEYS, "left").withColumn("amount_column", F.lit(amount_col))
    else:
        items = (
            items.withColumn("amounts_by_currency", F.lit(None).cast(AMOUNTS_TYPE))
            .withColumn("amount_column", F.lit(None).cast("string"))
        )

    return items.withColumn("source_table", F.lit(table))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build the items
# MAGIC
# MAGIC An item has a gap when any row was rejected or any currency's amount moved beyond the
# MAGIC tolerance. Gap items are `OPEN`; clean deliveries are kept as `MATCHED`, so the tab can show a
# MAGIC source delivered cleanly rather than only its problems.

# COMMAND ----------

items = None
for table in SOURCE_TABLES:
    part = reconcile_table(table)
    items = part if items is None else items.unionByName(part)

amount_moved = F.coalesce(
    F.exists(F.map_values("amounts_by_currency"), lambda v: F.abs(v["gap"]) > AMOUNT_TOLERANCE),
    F.lit(False),
)

pipeline_reconciliation = (
    items.withColumn("rejected_rows", (F.col("received_rows") - F.col("clean_rows")).cast("long"))
    .withColumn("has_gap", (F.col("rejected_rows") > 0) | amount_moved)
    .withColumn("status", F.when(F.col("has_gap"), F.lit("OPEN")).otherwise(F.lit("MATCHED")))
    .withColumn("recon_key", F.concat_ws("|", "ingest_batch_id", "source_system", "source_country", "source_table"))
    .withColumn("detected_at", F.current_timestamp())
    .select(
        "recon_key", "ingest_batch_id", "source_system", "source_country", "source_table",
        F.col("received_rows").cast("long").alias("received_rows"),
        F.col("clean_rows").cast("long").alias("clean_rows"),
        "rejected_rows", "amount_column", "unreadable_amount_rows", "amounts_by_currency",
        "has_gap", "status", "detected_at",
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Merge into `pipeline_reconciliation`
# MAGIC
# MAGIC Insert-only on `recon_key` (which includes the run): rerunning this notebook on the same run
# MAGIC adds nothing, a new Notebook 1 run adds new items, and a status the application has set
# MAGIC (FLOW-5's review) is never reset — same discipline as `flagged_transactions`.

# COMMAND ----------

if spark.catalog.tableExists("pipeline_reconciliation"):
    (
        DeltaTable.forName(spark, "pipeline_reconciliation").alias("t")
        .merge(pipeline_reconciliation.alias("s"), "t.recon_key = s.recon_key")
        .whenNotMatchedInsertAll()
        .execute()
    )
else:
    pipeline_reconciliation.write.format("delta").mode("overwrite").saveAsTable("pipeline_reconciliation")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

latest_batch = spark.table("raw_transactions").select("ingest_batch_id").first()[0]
this_run = spark.table("pipeline_reconciliation").filter(F.col("ingest_batch_id") == latest_batch)
print(f"run {latest_batch}: {this_run.count()} items, {this_run.filter('has_gap').count()} with a gap")
display(this_run.orderBy(F.col("has_gap").desc(), "source_table", "source_country"))
