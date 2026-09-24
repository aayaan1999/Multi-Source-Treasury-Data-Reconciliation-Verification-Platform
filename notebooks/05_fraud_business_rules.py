# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
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

import json
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

# Rule thresholds (FRD-3): read from Neon's app_settings['fraud.rules'] so the bank's own values
# can be set without code changes; these built-in defaults (the same values migration 013 seeds)
# apply if Neon or the setting isn't reachable. Illustrative POC values - spec section 3.
DEFAULT_RULES = {
    "large_amount_usd": 50_000,
    "velocity_count": 2,                 # more than this many same-day txns on one account
    "structuring_lower": 8_500,
    "structuring_upper": 10_000,         # exclusive
    "dormant_days": 180,                 # no activity for this long, then...
    "dormant_min_usd": 10_000,           # ...a transaction at least this big
    "pass_through_window_days": 1,       # money out within this many days of coming in
    "pass_through_min_share": 0.9,       # at least this share of what came in
    "pass_through_min_usd": 10_000,
    "segment_multiplier": 10,            # this many times the segment's typical transaction
    "segment_min_usd": 5_000,
    "round_step": 1_000,                 # "round" = a multiple of this
    "round_min_usd": 5_000,
    "round_min_count": 3,                # this many round amounts on one account in a day
    "split_min_accounts": 2,             # one customer, in the structuring band, on this many accounts
}


def load_rule_settings() -> dict:
    try:
        row = (
            spark.read.format("postgresql")
            .option("host", dbutils.secrets.get("neon", "host")).option("port", "5432")
            .option("database", dbutils.secrets.get("neon", "database"))
            .option("user", dbutils.secrets.get("neon", "user")).option("password", dbutils.secrets.get("neon", "password"))
            .option("dbtable", "public.app_settings")
            .load()
            .filter(F.col("key") == "fraud.rules")
            .select(F.col("value").cast("string").alias("value"))
            .first()
        )
        if row is None:
            raise LookupError("no fraud.rules row")
        return {**DEFAULT_RULES, **json.loads(row.value)}
    except Exception as e:  # no table yet (migration 013), no secrets, Neon asleep: use the defaults
        print(f"Using built-in rule thresholds - couldn't read app_settings from Neon: {type(e).__name__}: {str(e)[:200]}")
        return dict(DEFAULT_RULES)


RULES = load_rule_settings()
LARGE_AMOUNT_THRESHOLD_USD = RULES["large_amount_usd"]
VELOCITY_BREACH_COUNT = RULES["velocity_count"]
STRUCTURING_LOWER_BOUND = RULES["structuring_lower"]
STRUCTURING_UPPER_BOUND = RULES["structuring_upper"]
print("rule thresholds:", RULES)

# What kind of alert each rule raises (client feedback 2026-09-23, FRD-1: a large amount alone is
# not fraud). This is the value written to `flag_type`, and the Camunda bridge routes on it:
#   THRESHOLD   - a reporting event: the amount crossed a limit, nothing more is implied
#   SUSPICIOUS  - a pattern worth an investigator's judgment (unusual activity, AML red flag)
#   OPERATIONAL - a processing fault to correct, not a customer-behaviour concern
# Replaces the earlier FRAUD / FAULT split, where three of the four rules were called FRAUD.
FLAG_TYPE_BY_LABEL = {
    "LARGE_AMOUNT": "THRESHOLD",
    "VELOCITY_BREACH": "SUSPICIOUS",
    "STRUCTURING_PATTERN": "SUSPICIOUS",
    "DUPLICATE_TRANSACTION": "OPERATIONAL",
    # FRD-2's suspicious patterns (below): all genuine investigation matters.
    "DORMANT_REACTIVATION": "SUSPICIOUS",
    "PASS_THROUGH": "SUSPICIOUS",
    "UNUSUAL_FOR_SEGMENT": "SUSPICIOUS",
    "ROUND_AMOUNTS": "SUSPICIOUS",
    "SPLIT_ACROSS_ACCOUNTS": "SUSPICIOUS",
}

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
# MAGIC ## Rule 1 — `LARGE_AMOUNT` (THRESHOLD)

# COMMAND ----------

large_amount_flags = transactions_usd.filter(F.col("amount_usd") > LARGE_AMOUNT_THRESHOLD_USD).select(
    "transaction_id",
    F.lit("LARGE_AMOUNT").alias("flag_label"),
    F.lit(FLAG_TYPE_BY_LABEL["LARGE_AMOUNT"]).alias("flag_type"),
    F.concat(
        F.lit("amount "), F.format_number("amount_usd", 2), F.lit(" USD exceeds "),
        F.lit(str(LARGE_AMOUNT_THRESHOLD_USD)), F.lit(" USD threshold"),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 2 — `VELOCITY_BREACH` (SUSPICIOUS)
# MAGIC
# MAGIC More than `VELOCITY_BREACH_COUNT` transactions for the same account on the same date.

# COMMAND ----------

velocity_window = Window.partitionBy("account_id", "date")
txn_with_velocity = transactions_clean.withColumn("same_day_count", F.count("*").over(velocity_window))

velocity_flags = txn_with_velocity.filter(F.col("same_day_count") > VELOCITY_BREACH_COUNT).select(
    "transaction_id",
    F.lit("VELOCITY_BREACH").alias("flag_label"),
    F.lit(FLAG_TYPE_BY_LABEL["VELOCITY_BREACH"]).alias("flag_type"),
    F.concat(
        F.col("same_day_count").cast("string"),
        F.lit(" transactions for account "), F.col("account_id"),
        F.lit(" on "), F.col("date").cast("string"),
        F.lit(" exceeds threshold of "), F.lit(str(VELOCITY_BREACH_COUNT)),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 3 — `STRUCTURING_PATTERN` (SUSPICIOUS)
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
    F.lit(FLAG_TYPE_BY_LABEL["STRUCTURING_PATTERN"]).alias("flag_type"),
    F.concat(
        F.lit("amount "), F.abs(F.col("amount")).cast("string"), F.lit(" "), F.col("currency"),
        F.lit(" is in the "), F.lit(str(STRUCTURING_LOWER_BOUND)), F.lit("-"), F.lit(str(STRUCTURING_UPPER_BOUND)),
        F.lit(" band, with "), F.col("band_count_same_day").cast("string"),
        F.lit(" such transactions on account "), F.col("account_id"), F.lit(" the same day"),
    ).alias("description"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rule 4 — `DUPLICATE_TRANSACTION` (OPERATIONAL)
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
    F.lit(FLAG_TYPE_BY_LABEL["DUPLICATE_TRANSACTION"]).alias("flag_type"),
    F.concat(F.lit("matches transaction "), F.col("matched_transaction_id"), F.lit(" on account_id/amount/currency/type/date")).alias("description"),
).dropDuplicates(["transaction_id"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Suspicious patterns (FRD-2)
# MAGIC
# MAGIC Five more patterns the bank's review asked for (client point 5: "find other such examples"),
# MAGIC all `SUSPICIOUS`, all from data we already have. Amounts compared across currencies use the
# MAGIC live USD conversion above; thresholds come from `RULES`.

# COMMAND ----------

accounts_clean = spark.table("accounts_clean")
customers_clean = spark.table("customers_clean")
signed_usd = transactions_usd.withColumn("signed_usd", F.when(F.col("amount") < 0, -F.col("amount_usd")).otherwise(F.col("amount_usd")))

# Rule 5 - DORMANT_REACTIVATION: the account's previous transaction was at least `dormant_days`
# earlier, and this one is large. Needs history longer than the gap, so it can only fire once the
# data spans that long.
by_account_date = Window.partitionBy("account_id").orderBy("date", "transaction_id")
dormant_flags = (
    transactions_usd.withColumn("prev_date", F.lag("date").over(by_account_date))
    .filter(F.col("prev_date").isNotNull()
            & (F.datediff("date", "prev_date") >= RULES["dormant_days"])
            & (F.col("amount_usd") >= RULES["dormant_min_usd"]))
    .select(
        "transaction_id",
        F.lit("DORMANT_REACTIVATION").alias("flag_label"),
        F.lit("SUSPICIOUS").alias("flag_type"),
        F.concat(F.lit("no activity for "), F.datediff("date", "prev_date").cast("string"),
                 F.lit(" days, then "), F.format_number("amount_usd", 2), F.lit(" USD")).alias("description"),
    )
)

# Rule 6 - PASS_THROUGH: money comes in and (nearly all of) it goes straight out again. Both the
# inflow and the outflow are flagged.
inflows = signed_usd.filter((F.col("signed_usd") > 0) & (F.col("amount_usd") >= RULES["pass_through_min_usd"])).alias("i")
outflows = signed_usd.filter(F.col("signed_usd") < 0).alias("o")
pass_pairs = inflows.join(
    outflows,
    (F.col("i.account_id") == F.col("o.account_id"))
    & (F.datediff(F.col("o.date"), F.col("i.date")).between(0, RULES["pass_through_window_days"]))
    & (F.col("o.amount_usd") >= F.col("i.amount_usd") * RULES["pass_through_min_share"]),
)
pass_through_flags = (
    pass_pairs.select(F.col("i.transaction_id").alias("transaction_id"), F.col("o.transaction_id").alias("other"), F.col("i.amount_usd").alias("in_usd"))
    .unionByName(pass_pairs.select(F.col("o.transaction_id").alias("transaction_id"), F.col("i.transaction_id").alias("other"), F.col("i.amount_usd").alias("in_usd")))
    .dropDuplicates(["transaction_id"])
    .select(
        "transaction_id",
        F.lit("PASS_THROUGH").alias("flag_label"),
        F.lit("SUSPICIOUS").alias("flag_type"),
        F.concat(F.format_number("in_usd", 2), F.lit(" USD in and out again within "),
                 F.lit(str(RULES["pass_through_window_days"])), F.lit(" day(s), paired with "), F.col("other")).alias("description"),
    )
)

# Rule 7 - UNUSUAL_FOR_SEGMENT: far bigger than what's typical for the customer's segment (the
# segment's median transaction, in USD).
with_segment = (
    transactions_usd.join(accounts_clean.select("account_id", "customer_id"), "account_id")
    .join(customers_clean.select("customer_id", "segment"), "customer_id")
)
segment_typical = with_segment.groupBy("segment").agg(F.percentile_approx("amount_usd", 0.5).alias("typical_usd"))
unusual_flags = (
    with_segment.join(segment_typical, "segment")
    .filter((F.col("amount_usd") > F.col("typical_usd") * RULES["segment_multiplier"]) & (F.col("amount_usd") >= RULES["segment_min_usd"]))
    .select(
        "transaction_id",
        F.lit("UNUSUAL_FOR_SEGMENT").alias("flag_label"),
        F.lit("SUSPICIOUS").alias("flag_type"),
        F.concat(F.format_number("amount_usd", 2), F.lit(" USD is over "), F.lit(str(RULES["segment_multiplier"])),
                 F.lit("x the typical "), F.col("segment"), F.lit(" transaction ("), F.format_number("typical_usd", 2), F.lit(" USD)")).alias("description"),
    )
)

# Rule 8 - ROUND_AMOUNTS: several exactly-round, sizeable amounts on one account in a day.
is_round = (F.abs(F.col("amount")) % RULES["round_step"] == 0) & (F.col("amount_usd") >= RULES["round_min_usd"])
by_account_day = Window.partitionBy("account_id", "date")
round_flags = (
    transactions_usd.withColumn("is_round", is_round)
    .withColumn("round_count", F.sum(F.col("is_round").cast("int")).over(by_account_day))
    .filter(F.col("is_round") & (F.col("round_count") >= RULES["round_min_count"]))
    .select(
        "transaction_id",
        F.lit("ROUND_AMOUNTS").alias("flag_label"),
        F.lit("SUSPICIOUS").alias("flag_type"),
        F.concat(F.col("round_count").cast("string"), F.lit(" round amounts on account "), F.col("account_id"),
                 F.lit(" on "), F.col("date").cast("string")).alias("description"),
    )
)

# Rule 9 - SPLIT_ACROSS_ACCOUNTS: one customer, same day, amounts just under the reporting band on
# several of their accounts (Rule 3 only sees one account at a time).
in_band_customer = (
    transactions_clean.join(accounts_clean.select("account_id", "customer_id"), "account_id")
    .filter((F.abs(F.col("amount")) >= STRUCTURING_LOWER_BOUND) & (F.abs(F.col("amount")) < STRUCTURING_UPPER_BOUND))
    .withColumn("accounts_that_day", F.size(F.collect_set("account_id").over(Window.partitionBy("customer_id", "date"))))
)
split_flags = (
    in_band_customer.filter(F.col("accounts_that_day") >= RULES["split_min_accounts"])
    .select(
        "transaction_id",
        F.lit("SPLIT_ACROSS_ACCOUNTS").alias("flag_label"),
        F.lit("SUSPICIOUS").alias("flag_type"),
        F.concat(F.lit("customer "), F.col("customer_id"), F.lit(" has amounts in the "),
                 F.lit(str(STRUCTURING_LOWER_BOUND)), F.lit("-"), F.lit(str(STRUCTURING_UPPER_BOUND)),
                 F.lit(" band on "), F.col("accounts_that_day").cast("string"), F.lit(" accounts on "), F.col("date").cast("string")).alias("description"),
    )
)

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
    .unionByName(dormant_flags)
    .unionByName(pass_through_flags)
    .unionByName(unusual_flags)
    .unionByName(round_flags)
    .unionByName(split_flags)
    .withColumn("status", F.lit("PENDING_REVIEW"))
    .withColumn("detected_at", F.current_timestamp())
)

if spark.catalog.tableExists("flagged_transactions"):
    target = DeltaTable.forName(spark, "flagged_transactions")
    # Bring rows written before the FRAUD/FAULT -> THRESHOLD/SUSPICIOUS/OPERATIONAL relabel in line
    # with FLAG_TYPE_BY_LABEL. Only `flag_type` changes; `status` (the reviewer's decision) is left
    # untouched. After the first run this matches no rows, so it is safe on every rerun. Needed
    # because the Postgres load stages every Delta row and Postgres' CHECK rejects the old values.
    flag_type_expr = F.create_map([F.lit(x) for pair in FLAG_TYPE_BY_LABEL.items() for x in pair])[F.col("flag_label")]
    target.update(condition=F.col("flag_type") != flag_type_expr, set={"flag_type": flag_type_expr})
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