# Databricks notebook source
# MAGIC %md
# MAGIC # Notebook 2: Data Quality Verification
# MAGIC
# MAGIC Reads `treasury_positions_raw` (Notebook 1's output) and runs the eight checks from the
# MAGIC POC brief against every row. A row can trip more than one check — each tripped check
# MAGIC produces its own exception record, and a row only lands in the clean table if it trips
# MAGIC none of them.
# MAGIC
# MAGIC Input: Delta table `treasury_positions_raw`
# MAGIC Output: Delta tables `treasury_positions_clean`, `treasury_positions_exceptions`

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, StringType, StructType, StructField

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC - `VALID_CURRENCY_CODES`: recognised ISO-style codes. A currency pair is only valid if both
# MAGIC   sides are in this set — this is what separates a pair Notebook 1 could already fix by
# MAGIC   inserting a slash (`USDSAR` → `USD/SAR`) from one that's genuinely wrong (`QR/USD`, `XYZ/USD`).
# MAGIC - `PAIR_EXPECTED_RATE`: expected `counter_currency_amount / notional_amount` ratio per pair,
# MAGIC   used by the reconciliation check. A pair not listed here is skipped by that check rather
# MAGIC   than flagged — we can't judge reconciliation without a known expected rate for it.
# MAGIC - `RECONCILIATION_TOLERANCE`: fractional tolerance (5%) before a counter-amount deviation
# MAGIC   counts as a mismatch, to avoid flagging normal rounding.

# COMMAND ----------

dbutils.widgets.text("input_table", "treasury_positions_raw", "Input Delta table name")
dbutils.widgets.text("clean_table", "treasury_positions_clean", "Clean output table name")
dbutils.widgets.text("exceptions_table", "treasury_positions_exceptions", "Exceptions output table name")

INPUT_TABLE = dbutils.widgets.get("input_table")
CLEAN_TABLE = dbutils.widgets.get("clean_table")
EXCEPTIONS_TABLE = dbutils.widgets.get("exceptions_table")

VALID_CURRENCY_CODES = {"USD", "EUR", "LBP", "SAR", "QAR"}

# Expected counter/notional ratio per currency pair (mirrors the hardcoded FX assumptions
# used when standardising to USD in Notebook 1).
PAIR_EXPECTED_RATE = {
    "USD/LBP": 1500.0,
    "EUR/USD": 1.0,
    "USD/SAR": 3.75,
    "USD/QAR": 3.64,
}

RECONCILIATION_TOLERANCE = 0.05  # 5%

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load input

# COMMAND ----------

positions = spark.table(INPUT_TABLE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Row-level checks (checks 1-6)
# MAGIC
# MAGIC These six checks only need the row itself, unlike the duplicate/cross-entity checks below
# MAGIC which need to compare a row against others. Each check produces a nullable `(flag, description)`
# MAGIC struct — null when the check passes.

# COMMAND ----------

def flag_struct(condition, flag_label: str, description):
    """Returns a (flag_label, description) struct when `condition` is true, else null."""
    return F.when(
        condition,
        F.struct(F.lit(flag_label).alias("flag_label"), description.alias("description")),
    )


pair_rate_map = F.create_map(*[x for pair, rate in PAIR_EXPECTED_RATE.items() for x in (F.lit(pair), F.lit(rate))])
valid_ccy_pair = (
    F.col("currency_pair").rlike("^[A-Z]{3}/[A-Z]{3}$")
    & F.substring("currency_pair", 1, 3).isin(list(VALID_CURRENCY_CODES))
    & F.substring("currency_pair", 5, 3).isin(list(VALID_CURRENCY_CODES))
)
expected_rate = pair_rate_map[F.col("currency_pair")]
expected_counter = F.col("notional_amount") * expected_rate
reconciliation_deviation = F.abs(F.col("counter_currency_amount") - expected_counter) / expected_counter

checked = positions.select(
    "*",
    flag_struct(
        F.col("trade_date").isNull(), "MISSING_DATE", F.lit("trade_date is missing")
    ).alias("chk_missing_date"),
    flag_struct(
        F.col("trader_id").isNull() | (F.trim(F.col("trader_id")) == ""),
        "MISSING_TRADER",
        F.lit("trader_id is missing"),
    ).alias("chk_missing_trader"),
    flag_struct(
        ~valid_ccy_pair,
        "INVALID_CCY_PAIR",
        F.concat(F.lit("currency_pair '"), F.coalesce(F.col("currency_pair"), F.lit("")), F.lit("' is not a recognised XXX/YYY pair")),
    ).alias("chk_invalid_ccy_pair"),
    flag_struct(
        F.col("notional_amount").isNull() | (F.col("notional_amount") == 0),
        "INVALID_AMOUNT",
        F.lit("notional_amount is non-numeric, missing, or zero"),
    ).alias("chk_invalid_amount"),
    flag_struct(
        expected_rate.isNotNull()
        & F.col("notional_amount").isNotNull()
        & (F.col("notional_amount") != 0)
        & F.col("counter_currency_amount").isNotNull()
        & (reconciliation_deviation > RECONCILIATION_TOLERANCE),
        "RECONCILIATION_MISMATCH",
        F.concat(
            F.lit("counter_currency_amount "), F.col("counter_currency_amount").cast("string"),
            F.lit(" deviates from expected "), F.round(expected_counter, 2).cast("string"),
            F.lit(" by more than "), F.lit(str(int(RECONCILIATION_TOLERANCE * 100))), F.lit("%"),
        ),
    ).alias("chk_reconciliation_mismatch"),
    flag_struct(
        F.col("notional_amount").isNotNull()
        & F.col("limit_threshold").isNotNull()
        & (F.col("notional_amount") > F.col("limit_threshold")),
        "LIMIT_BREACH",
        F.concat(
            F.lit("notional_amount "), F.col("notional_amount").cast("string"),
            F.lit(" exceeds limit_threshold "), F.col("limit_threshold").cast("string"),
        ),
    ).alias("chk_limit_breach"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Duplicate check (check 7): `DUPLICATE_RECORD`
# MAGIC
# MAGIC Flags every row whose `trade_id` appears more than once *within the same entity*. Both
# MAGIC (or all) copies are flagged, not just the second occurrence, so a reviewer in Appian sees
# MAGIC every instance of the duplicate.

# COMMAND ----------

dup_counts = checked.groupBy("entity_code", "trade_id").agg(F.count("*").alias("dup_count"))

checked = checked.join(dup_counts, on=["entity_code", "trade_id"], how="left").withColumn(
    "chk_duplicate_record",
    flag_struct(
        F.col("dup_count") > 1,
        "DUPLICATE_RECORD",
        F.concat(F.lit("trade_id '"), F.col("trade_id"), F.lit("' appears "), F.col("dup_count").cast("string"), F.lit(" times for entity "), F.col("entity_code")),
    ),
).drop("dup_count")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cross-entity check (check 8): `CROSS_ENTITY_MISMATCH`
# MAGIC
# MAGIC The same `trade_id` can legitimately appear in two entities' books (e.g. an inter-entity
# MAGIC trade booked on both sides). It's only an exception when the USD-equivalent amount recorded
# MAGIC for it disagrees beyond tolerance between entities — this check compares `base_currency_amount_usd`
# MAGIC across every pair of entities sharing a `trade_id`.

# COMMAND ----------

by_trade = checked.select("trade_id", "entity_code", "base_currency_amount_usd").distinct()

cross_entity_pairs = (
    by_trade.alias("a")
    .join(by_trade.alias("b"), on="trade_id")
    .where(F.col("a.entity_code") < F.col("b.entity_code"))  # each unordered pair once
    .where(
        F.col("a.base_currency_amount_usd").isNotNull()
        & F.col("b.base_currency_amount_usd").isNotNull()
        & (
            F.abs(F.col("a.base_currency_amount_usd") - F.col("b.base_currency_amount_usd"))
            / F.greatest(F.abs(F.col("a.base_currency_amount_usd")), F.lit(0.01))
            > RECONCILIATION_TOLERANCE
        )
    )
    .select(F.col("trade_id").alias("mismatch_trade_id"))
    .distinct()
)

mismatched_trade_ids = [row.mismatch_trade_id for row in cross_entity_pairs.collect()]

checked = checked.withColumn(
    "chk_cross_entity_mismatch",
    flag_struct(
        F.col("trade_id").isin(mismatched_trade_ids),
        "CROSS_ENTITY_MISMATCH",
        F.concat(F.lit("trade_id '"), F.col("trade_id"), F.lit("' has a different amount recorded in another entity's file")),
    ),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Combine checks, split clean vs. exceptions

# COMMAND ----------

CHECK_COLUMNS = [
    "chk_missing_date",
    "chk_missing_trader",
    "chk_invalid_ccy_pair",
    "chk_invalid_amount",
    "chk_reconciliation_mismatch",
    "chk_limit_breach",
    "chk_duplicate_record",
    "chk_cross_entity_mismatch",
]

checked = checked.withColumn(
    "flags",
    F.array_compact(F.array(*CHECK_COLUMNS)),
).drop(*CHECK_COLUMNS)

BASE_COLUMNS = [c for c in positions.columns]

treasury_positions_clean = checked.filter(F.size("flags") == 0).select(*BASE_COLUMNS)

treasury_positions_exceptions = (
    checked.filter(F.size("flags") > 0)
    .select(*BASE_COLUMNS, F.explode("flags").alias("flag"))
    .select(*BASE_COLUMNS, F.col("flag.flag_label").alias("flag_label"), F.col("flag.description").alias("description"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write outputs

# COMMAND ----------

(
    treasury_positions_clean.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(CLEAN_TABLE)
)

(
    treasury_positions_exceptions.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(EXCEPTIONS_TABLE)
)

display(spark.table(EXCEPTIONS_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"Clean rows: {spark.table(CLEAN_TABLE).count()}")
print(f"Exception records: {spark.table(EXCEPTIONS_TABLE).count()}")
spark.table(EXCEPTIONS_TABLE).groupBy("flag_label").count().orderBy(F.desc("count")).show()
spark.table(EXCEPTIONS_TABLE).groupBy("entity_code", "flag_label").count().orderBy("entity_code", "flag_label").show(50)
