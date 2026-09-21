# Databricks notebook source
# MAGIC %md
# MAGIC # Notebook 5: Fraud & Business Rule Detection
# MAGIC
# MAGIC Runs 4 illustrative POC rules against `transactions_clean`, per
# MAGIC `specs/notebook-05-fraud-business-rules.md`. Separate from Notebook 2's data-quality checks
# MAGIC on purpose (section 2 of that spec): a broken record needs data correction, a suspicious
# MAGIC one needs an investigator's judgment — different downstream handling.
# MAGIC
# MAGIC **This is the one notebook in the pipeline that isn't a clean overwrite-on-rerun.** Once a
# MAGIC flagged row's `status` has been updated by a reviewer (via the bidirectional sync), a
# MAGIC rerun of this notebook must not reset it back to `PENDING_REVIEW` — hence `MERGE INTO`
# MAGIC instead of `overwrite` on the final write.
# MAGIC
# MAGIC LARGE_AMOUNT's USD conversion uses `fx_utils.get_live_rate()`, consistent with the
# MAGIC platform-wide move away from a static `fx_rates_clean` lookup (`specs/fx-realtime-ingestion.md`)
# MAGIC — even though that spec's acceptance criteria only names Notebooks 3/6 explicitly, there's no
# MAGIC reason for a new notebook to depend on a table being phased out.
# MAGIC
# MAGIC Input: `transactions_clean`
# MAGIC Output: Delta table `flagged_transactions` (merge, not overwrite)

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

# MAGIC %run ./fx_utils

# COMMAND ----------

import uuid
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from delta.tables import DeltaTable

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC Thresholds are illustrative POC values, not sourced from an actual regulator requirement —
# MAGIC see spec section 3.

# COMMAND ----------

LARGE_AMOUNT_THRESHOLD_USD = 50_000
VELOCITY_BREACH_COUNT = 2  # more than this many same-day txns on one account
STRUCTURING_LOWER_BOUND = 8_500
STRUCTURING_UPPER_BOUND = 10_000  # exclusive

NOTEBOOK_RUN_ID = str(uuid.uuid4())

# COMMAND ----------

transactions_clean = spark.table("transactions_clean")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Live USD conversion (for `LARGE_AMOUNT` only — the other 3 rules compare native-currency
# MAGIC or same-account values, so no conversion is needed for them)

# COMMAND ----------

txn_currencies = [r.currency for r in transactions_clean.select("currency").distinct().collect()]
rate_map = {"USD": 1.0}
for ccy in txn_currencies:
    if ccy is None or ccy == "USD":
        continue
    rate_map[ccy] = get_live_rate_and_log(f"USD/{ccy}", NOTEBOOK_RUN_ID, "large_amount_rule")

rate_map_expr = F.create_map([F.lit(x) for pair in rate_map.items() for x in pair])
transactions_usd = transactions_clean.withColumn(
    "amount_usd", F.abs(F.col("amount")) / rate_map_expr[F.col("currency")]
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 1 — `LARGE_AMOUNT` (FRAUD)

# COMMAND ----------

large_amount_flags = transactions_usd.filter(F.col("amount_usd") > LARGE_AMOUNT_THRESHOLD_USD).select(
    "transaction_id",
    F.lit("LARGE_AMOUNT").alias("flag_label"),
    F.lit("FRAUD").alias("flag_type"),
    F.concat(
        F.lit("amount "), F.format_number("amount_usd", 2), F.lit(" USD exceeds "),
        F.lit(str(LARGE_AMOUNT_THRESHOLD_USD)), F.lit(" USD threshold"),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 2 — `VELOCITY_BREACH` (FRAUD)
# MAGIC
# MAGIC More than `VELOCITY_BREACH_COUNT` transactions for the same account on the same date.

# COMMAND ----------

velocity_window = Window.partitionBy("account_id", "date")
txn_with_velocity = transactions_clean.withColumn("same_day_count", F.count("*").over(velocity_window))

velocity_flags = txn_with_velocity.filter(F.col("same_day_count") > VELOCITY_BREACH_COUNT).select(
    "transaction_id",
    F.lit("VELOCITY_BREACH").alias("flag_label"),
    F.lit("FRAUD").alias("flag_type"),
    F.concat(
        F.col("same_day_count").cast("string"),
        F.lit(" transactions for account "), F.col("account_id"),
        F.lit(" on "), F.col("date").cast("string"),
        F.lit(" exceeds threshold of "), F.lit(str(VELOCITY_BREACH_COUNT)),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 3 — `STRUCTURING_PATTERN` (FRAUD)
# MAGIC
# MAGIC Native-currency amount just under a round reporting threshold, with 2+ such transactions on
# MAGIC the same account/date — a single near-threshold transaction alone isn't structuring, the
# MAGIC repetition is what the pattern actually flags.

# COMMAND ----------

in_band = transactions_clean.withColumn(
    "in_structuring_band",
    (F.abs(F.col("amount")) >= STRUCTURING_LOWER_BOUND) & (F.abs(F.col("amount")) < STRUCTURING_UPPER_BOUND),
)

structuring_window = Window.partitionBy("account_id", "date")
in_band_with_count = in_band.withColumn(
    "band_count_same_day", F.sum(F.col("in_structuring_band").cast("int")).over(structuring_window)
)

structuring_flags = in_band_with_count.filter(
    F.col("in_structuring_band") & (F.col("band_count_same_day") >= 2)
).select(
    "transaction_id",
    F.lit("STRUCTURING_PATTERN").alias("flag_label"),
    F.lit("FRAUD").alias("flag_type"),
    F.concat(
        F.lit("amount "), F.abs(F.col("amount")).cast("string"), F.lit(" "), F.col("currency"),
        F.lit(" is in the "), F.lit(str(STRUCTURING_LOWER_BOUND)), F.lit("-"), F.lit(str(STRUCTURING_UPPER_BOUND)),
        F.lit(" band, with "), F.col("band_count_same_day").cast("string"),
        F.lit(" such transactions on account "), F.col("account_id"), F.lit(" the same day"),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 4 — `DUPLICATE_TRANSACTION` (FAULT)
# MAGIC
# MAGIC Self-join on `(account_id, amount, currency, type, date)` excluding self-matches — every
# MAGIC row in a duplicate group gets flagged, not just the second one, since there's no reliable
# MAGIC "which one is the original" signal in this schema.

# COMMAND ----------

dup_key_cols = ["account_id", "amount", "currency", "type", "date"]
left = transactions_clean.alias("a")
right = transactions_clean.alias("b")

duplicate_pairs = left.join(
    right,
    [(F.col(f"a.{c}") == F.col(f"b.{c}")) for c in dup_key_cols]
    + [F.col("a.transaction_id") != F.col("b.transaction_id")],
    "inner",
).select(F.col("a.transaction_id").alias("transaction_id"), F.col("b.transaction_id").alias("matched_transaction_id"))

duplicate_flags = duplicate_pairs.select(
    "transaction_id",
    F.lit("DUPLICATE_TRANSACTION").alias("flag_label"),
    F.lit("FAULT").alias("flag_type"),
    F.concat(F.lit("matches transaction "), F.col("matched_transaction_id"), F.lit(" on account_id/amount/currency/type/date")).alias("description"),
).dropDuplicates(["transaction_id"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Combine and merge
# MAGIC
# MAGIC A transaction can carry multiple flags (e.g. both `STRUCTURING_PATTERN` and
# MAGIC `VELOCITY_BREACH`) — each rule contributes its own row(s), same multi-flag design as
# MAGIC Notebook 2. `status` is set to `PENDING_REVIEW` only for genuinely new (transaction_id,
# MAGIC flag_label) pairs; existing rows keep whatever status a reviewer has already set.

# COMMAND ----------

all_flags = (
    large_amount_flags
    .unionByName(velocity_flags)
    .unionByName(structuring_flags)
    .unionByName(duplicate_flags)
    .withColumn("status", F.lit("PENDING_REVIEW"))
    .withColumn("detected_at", F.current_timestamp())
)

if spark.catalog.tableExists("flagged_transactions"):
    target = DeltaTable.forName(spark, "flagged_transactions")
    (
        target.alias("t")
        .merge(all_flags.alias("s"), "t.transaction_id = s.transaction_id AND t.flag_label = s.flag_label")
        .whenNotMatchedInsertAll()
        .execute()
    )
else:
    (
        all_flags.write.format("delta")
        .mode("overwrite")
        .saveAsTable("flagged_transactions")
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

flagged_transactions = spark.table("flagged_transactions")
print(f"flagged_transactions: {flagged_transactions.count()} rows")
display(flagged_transactions.orderBy("transaction_id", "flag_label"))
