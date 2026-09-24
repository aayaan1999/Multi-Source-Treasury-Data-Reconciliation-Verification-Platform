# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Notebook 2: Data Quality Verification
# MAGIC
# MAGIC Reads the eight `raw_*` tables from Notebook 1 and runs per-table structural checks plus
# MAGIC cross-table referential checks (does this `customer_id`/`account_id`/`branch_id` actually
# MAGIC exist?). Unlike the treasury pipeline's per-table exception table, findings across all
# MAGIC eight tables land in one central log (`data_quality_exceptions`) — the eight source tables
# MAGIC have almost no columns in common, so a single wide exceptions table per source table would
# MAGIC just be eight different shapes; a generic `(source_table, record_key, flag_label,
# MAGIC description)` log is what an analyst or Screen 6's task queue actually needs to route work.
# MAGIC
# MAGIC This replaces the earlier treasury-specific version of this notebook — see Notebook 1's
# MAGIC header and `CLAUDE.md` for why.
# MAGIC
# MAGIC Input: Delta tables `raw_customers`, `raw_accounts`, `raw_loans`, `raw_transactions`,
# MAGIC `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`, `raw_fx_rates`
# MAGIC Output: Delta tables `customers_clean`, `accounts_clean`, `loans_clean`,
# MAGIC `transactions_clean`, `branches_clean`, `capital_positions_clean`, `liquidity_daily_clean`,
# MAGIC `fx_rates_clean`, and one `data_quality_exceptions` table
# MAGIC
# MAGIC Notebook 1's source tags (`source_system`, `source_country`, `ingest_batch_id`,
# MAGIC `source_file` — `specs/source-tagging.md`) carry through: clean tables keep them because
# MAGIC every check selects `*`, and each exception copies them from the rejected row.

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

VALID_CURRENCY_CODES = {"USD", "EUR", "LBP", "SAR", "QAR"}
VALID_SEGMENTS = {"Retail", "SME", "Corporate"}
VALID_RISK_RATINGS = {"A", "B", "C", "D", "E"}
VALID_LOAN_STAGES = {1.0, 2.0, 3.0}
VALID_CHANNELS = {"Branch", "ATM", "Mobile", "Online"}
NPL_DAYS_PAST_DUE_THRESHOLD = 90

# Notebook 1's provenance columns, copied onto every exception so a rejected record still says which
# source, country, run and file it came from (reconciliation per source counts rejects by these).
SOURCE_TAG_COLS = ["source_system", "source_country", "ingest_batch_id", "source_file"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Helpers
# MAGIC
# MAGIC Same pattern as the treasury pipeline: each check produces a nullable `(flag_label,
# MAGIC description)` struct, non-null structs are collected into a `flags` array per row, a row
# MAGIC is clean only if that array is empty, and every non-empty array is exploded into the
# MAGIC central exceptions log.

# COMMAND ----------

def flag_struct(condition, flag_label: str, description):
    return F.when(
        condition,
        F.struct(F.lit(flag_label).alias("flag_label"), description.alias("description")),
    )


def finalize(df: DataFrame, table_name: str, key_col: str, check_cols: list):
    """Combines the named check columns into a `flags` array, splits the table into
    (clean_df, exceptions_df), and returns both. `exceptions_df` is already shaped to match
    the central `data_quality_exceptions` log."""
    df = df.withColumn("flags", F.array_compact(F.array(*check_cols))).drop(*check_cols)

    base_cols = [c for c in df.columns if c != "flags"]
    clean_df = df.filter(F.size("flags") == 0).select(*base_cols)

    exceptions_df = (
        df.filter(F.size("flags") > 0)
        .select(F.col(key_col).cast("string").alias("record_key"), F.explode("flags").alias("flag"), *SOURCE_TAG_COLS)
        .select(
            F.lit(table_name).alias("source_table"),
            "record_key",
            F.col("flag.flag_label").alias("flag_label"),
            F.col("flag.description").alias("description"),
            *SOURCE_TAG_COLS,
        )
    )
    return clean_df, exceptions_df


def orphan_flags(child_df: DataFrame, child_key_col: str, child_fk_col: str, parent_df: DataFrame, parent_key_col: str, flag_label: str, table_name: str):
    """Anti-joins child against parent on the foreign key and returns exception rows for every
    child record whose foreign key doesn't exist in the parent table.

    Callers pass the parent's *clean* table, not its raw one: a parent quarantined for any other
    reason (e.g. MISSING_RISK_RATING) must also take its children out of the clean set, otherwise a
    clean child would point at a row that isn't in the clean parent table and the PostgreSQL
    foreign keys would reject it at import. This is why Branches is processed before Customers,
    and Customers/Accounts before their children."""
    orphans = child_df.join(
        parent_df.select(F.col(parent_key_col).alias("_parent_key")),
        child_df[child_fk_col] == F.col("_parent_key"),
        "left_anti",
    )
    return orphans.select(
        F.lit(table_name).alias("source_table"),
        F.col(child_key_col).cast("string").alias("record_key"),
        F.lit(flag_label).alias("flag_label"),
        F.concat(F.lit(f"{child_fk_col} '"), F.col(child_fk_col), F.lit(f"' has no matching {parent_key_col} in the clean parent table")).alias("description"),
        *SOURCE_TAG_COLS,
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load raw tables

# COMMAND ----------

raw_customers = spark.table("raw_customers")
raw_accounts = spark.table("raw_accounts")
raw_loans = spark.table("raw_loans")
raw_transactions = spark.table("raw_transactions")
raw_branches = spark.table("raw_branches")
raw_capital_positions = spark.table("raw_capital_positions")
raw_liquidity_daily = spark.table("raw_liquidity_daily")
raw_fx_rates = spark.table("raw_fx_rates")

exception_frames = []

# COMMAND ----------

# MAGIC %md
# MAGIC ## Branches
# MAGIC
# MAGIC `MISSING_BRANCH_ID`, `NEGATIVE_OPEX`.

# COMMAND ----------

branches_checked = raw_branches.select(
    "*",
    flag_struct(F.col("branch_id").isNull(), "MISSING_BRANCH_ID", F.lit("branch_id is missing")).alias("chk_1"),
    flag_struct(
        F.col("monthly_opex").isNotNull() & (F.col("monthly_opex") < 0),
        "NEGATIVE_OPEX",
        F.concat(F.lit("monthly_opex "), F.col("monthly_opex").cast("string"), F.lit(" is negative")),
    ).alias("chk_2"),
)

branches_clean, branches_exceptions = finalize(branches_checked, "branches", "branch_id", ["chk_1", "chk_2"])
exception_frames.append(branches_exceptions)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Customers
# MAGIC
# MAGIC `MISSING_CUSTOMER_ID`, `MISSING_RISK_RATING`, `INVALID_SEGMENT`, `MISSING_BRANCH_ID`, plus
# MAGIC the cross-table `ORPHAN_BRANCH` (a `branch_id` that doesn't exist in `branches`).

# COMMAND ----------

customers_checked = raw_customers.select(
    "*",
    flag_struct(F.col("customer_id").isNull(), "MISSING_CUSTOMER_ID", F.lit("customer_id is missing")).alias("chk_1"),
    flag_struct(
        F.col("risk_rating").isNull() | (F.trim(F.col("risk_rating")) == ""),
        "MISSING_RISK_RATING",
        F.lit("risk_rating is missing"),
    ).alias("chk_2"),
    flag_struct(
        ~F.col("segment").isin(list(VALID_SEGMENTS)),
        "INVALID_SEGMENT",
        F.concat(F.lit("segment '"), F.coalesce(F.col("segment"), F.lit("")), F.lit("' is not one of Retail/SME/Corporate")),
    ).alias("chk_3"),
    flag_struct(F.col("branch_id").isNull(), "MISSING_BRANCH_ID", F.lit("branch_id is missing")).alias("chk_4"),
)

customers_clean, customers_exceptions = finalize(customers_checked, "customers", "customer_id", ["chk_1", "chk_2", "chk_3", "chk_4"])
exception_frames.append(customers_exceptions)
exception_frames.append(
    orphan_flags(raw_customers, "customer_id", "branch_id", branches_clean, "branch_id", "ORPHAN_BRANCH", "customers")
)
# Orphan customers get pulled out of the clean set too, not just logged.
customer_orphan_ids = [r.record_key for r in exception_frames[-1].select("record_key").distinct().collect()]
customers_clean = customers_clean.filter(~F.col("customer_id").isin(customer_orphan_ids))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Accounts
# MAGIC
# MAGIC `MISSING_ACCOUNT_ID`, `NEGATIVE_BALANCE`, `INVALID_CURRENCY`, plus `ORPHAN_CUSTOMER`.

# COMMAND ----------

accounts_checked = raw_accounts.select(
    "*",
    flag_struct(F.col("account_id").isNull(), "MISSING_ACCOUNT_ID", F.lit("account_id is missing")).alias("chk_1"),
    flag_struct(
        F.col("balance").isNotNull() & (F.col("balance") < 0),
        "NEGATIVE_BALANCE",
        F.concat(F.lit("balance "), F.col("balance").cast("string"), F.lit(" is negative")),
    ).alias("chk_2"),
    flag_struct(
        ~F.col("currency").isin(list(VALID_CURRENCY_CODES)),
        "INVALID_CURRENCY",
        F.concat(F.lit("currency '"), F.coalesce(F.col("currency"), F.lit("")), F.lit("' is not recognised")),
    ).alias("chk_3"),
)

accounts_clean, accounts_exceptions = finalize(accounts_checked, "accounts", "account_id", ["chk_1", "chk_2", "chk_3"])
exception_frames.append(accounts_exceptions)
accounts_orphan_exceptions = orphan_flags(raw_accounts, "account_id", "customer_id", customers_clean, "customer_id", "ORPHAN_CUSTOMER", "accounts")
exception_frames.append(accounts_orphan_exceptions)
account_orphan_ids = [r.record_key for r in accounts_orphan_exceptions.select("record_key").distinct().collect()]
accounts_clean = accounts_clean.filter(~F.col("account_id").isin(account_orphan_ids))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Loans
# MAGIC
# MAGIC `MISSING_LOAN_ID`, `OUTSTANDING_EXCEEDS_PRINCIPAL`, `INVALID_STAGE`, `NEGATIVE_DPD`,
# MAGIC `NPL_STAGE_MISMATCH` (days_past_due >= 90 but stage isn't 3 — the IFRS 9 definition from
# MAGIC the source doc says a loan that far past due should already be staged as impaired), plus
# MAGIC `ORPHAN_CUSTOMER`.

# COMMAND ----------

loans_checked = raw_loans.select(
    "*",
    flag_struct(F.col("loan_id").isNull(), "MISSING_LOAN_ID", F.lit("loan_id is missing")).alias("chk_1"),
    flag_struct(
        F.col("outstanding").isNotNull() & F.col("principal").isNotNull() & (F.col("outstanding") > F.col("principal")),
        "OUTSTANDING_EXCEEDS_PRINCIPAL",
        F.concat(F.lit("outstanding "), F.col("outstanding").cast("string"), F.lit(" exceeds principal "), F.col("principal").cast("string")),
    ).alias("chk_2"),
    flag_struct(
        F.col("stage").isNotNull() & ~F.col("stage").isin(list(VALID_LOAN_STAGES)),
        "INVALID_STAGE",
        F.concat(F.lit("stage "), F.col("stage").cast("string"), F.lit(" is not 1, 2, or 3")),
    ).alias("chk_3"),
    flag_struct(
        F.col("days_past_due").isNotNull() & (F.col("days_past_due") < 0),
        "NEGATIVE_DPD",
        F.concat(F.lit("days_past_due "), F.col("days_past_due").cast("string"), F.lit(" is negative")),
    ).alias("chk_4"),
    flag_struct(
        (F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD) & (F.col("stage") != 3),
        "NPL_STAGE_MISMATCH",
        F.concat(
            F.lit("days_past_due "), F.col("days_past_due").cast("string"),
            F.lit(" is >= 90 but stage is "), F.col("stage").cast("string"), F.lit(", expected 3"),
        ),
    ).alias("chk_5"),
)

loans_clean, loans_exceptions = finalize(loans_checked, "loans", "loan_id", ["chk_1", "chk_2", "chk_3", "chk_4", "chk_5"])
exception_frames.append(loans_exceptions)
loans_orphan_exceptions = orphan_flags(raw_loans, "loan_id", "customer_id", customers_clean, "customer_id", "ORPHAN_CUSTOMER", "loans")
exception_frames.append(loans_orphan_exceptions)
loan_orphan_ids = [r.record_key for r in loans_orphan_exceptions.select("record_key").distinct().collect()]
loans_clean = loans_clean.filter(~F.col("loan_id").isin(loan_orphan_ids))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Transactions
# MAGIC
# MAGIC `MISSING_TRANSACTION_ID`, `INVALID_AMOUNT`, `INVALID_CHANNEL`, plus `ORPHAN_ACCOUNT`.

# COMMAND ----------

transactions_checked = raw_transactions.select(
    "*",
    flag_struct(F.col("transaction_id").isNull(), "MISSING_TRANSACTION_ID", F.lit("transaction_id is missing")).alias("chk_1"),
    flag_struct(F.col("amount").isNull(), "INVALID_AMOUNT", F.lit("amount is missing or non-numeric")).alias("chk_2"),
    flag_struct(
        ~F.col("channel").isin(list(VALID_CHANNELS)),
        "INVALID_CHANNEL",
        F.concat(F.lit("channel '"), F.coalesce(F.col("channel"), F.lit("")), F.lit("' is not one of Branch/ATM/Mobile/Online")),
    ).alias("chk_3"),
)

transactions_clean, transactions_exceptions = finalize(transactions_checked, "transactions", "transaction_id", ["chk_1", "chk_2", "chk_3"])
exception_frames.append(transactions_exceptions)
transactions_orphan_exceptions = orphan_flags(raw_transactions, "transaction_id", "account_id", accounts_clean, "account_id", "ORPHAN_ACCOUNT", "transactions")
exception_frames.append(transactions_orphan_exceptions)
transaction_orphan_ids = [r.record_key for r in transactions_orphan_exceptions.select("record_key").distinct().collect()]
transactions_clean = transactions_clean.filter(~F.col("transaction_id").isin(transaction_orphan_ids))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Capital positions
# MAGIC
# MAGIC `MISSING_MONTH`, `INVALID_RWA` (risk_weighted_assets must be positive — it's a denominator
# MAGIC for every capital ratio, so zero/negative breaks Screen 1 downstream).

# COMMAND ----------

capital_checked = raw_capital_positions.select(
    "*",
    flag_struct(
        F.col("month").isNull() | (F.trim(F.col("month")) == ""),
        "MISSING_MONTH",
        F.lit("month is missing"),
    ).alias("chk_1"),
    flag_struct(
        F.col("risk_weighted_assets").isNull() | (F.col("risk_weighted_assets") <= 0),
        "INVALID_RWA",
        F.concat(F.lit("risk_weighted_assets "), F.coalesce(F.col("risk_weighted_assets").cast("string"), F.lit("null")), F.lit(" must be positive")),
    ).alias("chk_2"),
)

capital_positions_clean, capital_positions_exceptions = finalize(capital_checked, "capital_positions", "month", ["chk_1", "chk_2"])
exception_frames.append(capital_positions_exceptions)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Liquidity daily
# MAGIC
# MAGIC `MISSING_DATE`, `NEGATIVE_HQLA`.

# COMMAND ----------

liquidity_checked = raw_liquidity_daily.select(
    "*",
    flag_struct(F.col("date").isNull(), "MISSING_DATE", F.lit("date is missing")).alias("chk_1"),
    flag_struct(
        F.col("hqla").isNotNull() & (F.col("hqla") < 0),
        "NEGATIVE_HQLA",
        F.concat(F.lit("hqla "), F.col("hqla").cast("string"), F.lit(" is negative")),
    ).alias("chk_2"),
)

liquidity_daily_clean, liquidity_daily_exceptions = finalize(liquidity_checked, "liquidity_daily", "date", ["chk_1", "chk_2"])
exception_frames.append(liquidity_daily_exceptions)

# COMMAND ----------

# MAGIC %md
# MAGIC ## FX rates
# MAGIC
# MAGIC `INVALID_RATE` (missing or <= 0), `DUPLICATE_RATE` (more than one rate for the same
# MAGIC date + currency_pair — ambiguous which one downstream conversions should use).

# COMMAND ----------

fx_dup_counts = raw_fx_rates.groupBy("date", "currency_pair").agg(F.count("*").alias("dup_count"))
fx_with_dups = raw_fx_rates.join(fx_dup_counts, on=["date", "currency_pair"], how="left")

# fx_rates has no single-column primary key — date + currency_pair together identify a rate —
# so build a composite key column upfront and pass that to finalize() as the "key_col".
fx_with_dups = fx_with_dups.withColumn(
    "fx_key", F.concat_ws("_", F.col("date").cast("string"), F.col("currency_pair"))
)

fx_checked = fx_with_dups.select(
    "*",
    flag_struct(
        F.col("rate").isNull() | (F.col("rate") <= 0),
        "INVALID_RATE",
        F.concat(F.lit("rate "), F.coalesce(F.col("rate").cast("string"), F.lit("null")), F.lit(" must be positive")),
    ).alias("chk_1"),
    flag_struct(
        F.col("dup_count") > 1,
        "DUPLICATE_RATE",
        F.concat(F.lit("currency_pair '"), F.col("currency_pair"), F.lit("' has "), F.col("dup_count").cast("string"), F.lit(" rates for date "), F.col("date").cast("string")),
    ).alias("chk_2"),
).drop("dup_count")

fx_rates_clean, fx_rates_exceptions = finalize(fx_checked, "fx_rates", "fx_key", ["chk_1", "chk_2"])
fx_rates_clean = fx_rates_clean.drop("fx_key")
exception_frames.append(fx_rates_exceptions)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write outputs

# COMMAND ----------

CLEAN_TABLES = {
    "customers_clean": customers_clean,
    "accounts_clean": accounts_clean,
    "loans_clean": loans_clean,
    "transactions_clean": transactions_clean,
    "branches_clean": branches_clean,
    "capital_positions_clean": capital_positions_clean,
    "liquidity_daily_clean": liquidity_daily_clean,
    "fx_rates_clean": fx_rates_clean,
}

for table_name, df in CLEAN_TABLES.items():
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table_name)
    )

data_quality_exceptions = exception_frames[0]
for df in exception_frames[1:]:
    data_quality_exceptions = data_quality_exceptions.unionByName(df)

(
    data_quality_exceptions.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable("data_quality_exceptions")
)

display(spark.table("data_quality_exceptions"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

for table_name in CLEAN_TABLES:
    print(f"{table_name}: {spark.table(table_name).count()} rows")

print(f"data_quality_exceptions: {spark.table('data_quality_exceptions').count()} rows")
spark.table("data_quality_exceptions").groupBy("source_table", "flag_label").count().orderBy("source_table", "flag_label").show(50)