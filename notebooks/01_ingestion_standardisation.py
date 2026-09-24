# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Notebook 1: Ingestion & Standardisation
# MAGIC
# MAGIC Reads the eight core banking tables described in `Middle East bank data cleaning and
# MAGIC reporting.md` (customers, accounts, loans, transactions, branches, capital_positions,
# MAGIC liquidity_daily, fx_rates), standardises each (dates, numeric types, currency-pair
# MAGIC notation), and writes one Delta table per source table.
# MAGIC
# MAGIC This replaces the earlier treasury-specific version of this notebook — the platform's
# MAGIC scope expanded from the three-entity treasury reconciliation brief to the full bank data
# MAGIC model. See `CLAUDE.md` for how the two source documents relate.
# MAGIC
# MAGIC Input: `customers.csv`, `accounts.csv`, `loans.csv`, `transactions.csv`, `branches.csv`,
# MAGIC `capital_positions.csv`, `liquidity_daily.csv`, `fx_rates.csv`
# MAGIC Output: Delta tables `raw_customers`, `raw_accounts`, `raw_loans`, `raw_transactions`,
# MAGIC `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`, `raw_fx_rates`
# MAGIC
# MAGIC Every output row is tagged with where it came from — `source_system`, `source_country`,
# MAGIC `ingest_batch_id`, `source_file` (`specs/source-tagging.md`) — so reconciliation can compare
# MAGIC each source's delivery with what survives cleaning.

# COMMAND ----------

# DBTITLE 1,Set catalog and schema
# Pin reads/writes to the existing workspace catalog so bare table names resolve the same
# way in every notebook (same pattern as Notebook 2 Cell 2).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

import uuid
from datetime import datetime, timezone

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC One entry per source table: its file name, which columns are dates (standardised to
# MAGIC `YYYY-MM-DD`), and which columns are numeric (cast via `try_cast`, so a malformed value
# MAGIC becomes null here rather than erroring — Notebook 2's checks are what flag the null, not
# MAGIC this notebook). `month` on `capital_positions` is handled separately since it's a
# MAGIC year-month, not a full date.

# COMMAND ----------

dbutils.widgets.text("input_dir", "/Volumes/dbw_bankx_treasury_poc/raw/raw/resources", "Input directory")

INPUT_DIR = dbutils.widgets.get("input_dir")

# Which source system this folder's files came from, and (for a single-country source) its country.
# Today one CSV set covers every country, so the defaults are a placeholder source name and a blank
# country, which makes each row take its branch's country instead (see "Source tags" below). Each
# real source (e.g. a country's ERP) will get its own landing folder and run with these set.
dbutils.widgets.text("source_system", "CORE_CSV", "Source system")
dbutils.widgets.text("source_country", "", "Source country (blank = each record's branch country)")
SOURCE_SYSTEM = dbutils.widgets.get("source_system").strip() or "CORE_CSV"
SOURCE_COUNTRY = dbutils.widgets.get("source_country").strip() or None

# One id for this whole run: every row loaded now shares it, so a later step can compare "what this
# delivery contained" with "what survived cleaning". Readable on its own: source, UTC time, short id.
INGEST_BATCH_ID = f"{SOURCE_SYSTEM}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"

# Branch region -> country, for a multi-country source. An assumption read off the region names in
# the sample data (specs/source-tagging.md section 3) - confirm with the bank.
REGION_COUNTRY = {
    "Beirut": "Lebanon", "North": "Lebanon", "South": "Lebanon", "Bekaa": "Lebanon", "Mount Lebanon": "Lebanon",
    "KSA": "Saudi Arabia",
    "Qatar": "Qatar",
}

VALID_CURRENCY_CODES = {"USD", "EUR", "LBP", "SAR", "QAR"}

TABLES = {
    "customers": {
        "file": "customers.csv",
        "date_cols": ["onboard_date"],
        "numeric_cols": [],
    },
    "accounts": {
        "file": "accounts.csv",
        "date_cols": ["open_date"],
        "numeric_cols": ["balance"],
    },
    "loans": {
        "file": "loans.csv",
        "date_cols": ["origination_date", "maturity_date"],
        "numeric_cols": [
            "principal", "outstanding", "interest_rate", "days_past_due",
            "stage", "provision_amount", "collateral_value",
        ],
    },
    "transactions": {
        "file": "transactions.csv",
        "date_cols": ["date"],
        "numeric_cols": ["amount"],
    },
    "branches": {
        "file": "branches.csv",
        "date_cols": [],
        "numeric_cols": ["staff_count", "monthly_opex"],
    },
    "capital_positions": {
        "file": "capital_positions.csv",
        "date_cols": [],
        "numeric_cols": ["tier1_capital", "tier2_capital", "risk_weighted_assets"],
    },
    "liquidity_daily": {
        "file": "liquidity_daily.csv",
        "date_cols": ["date"],
        "numeric_cols": ["hqla", "net_outflows_30d", "stable_funding", "required_funding"],
    },
    "fx_rates": {
        "file": "fx_rates.csv",
        "date_cols": ["date"],
        "numeric_cols": ["rate"],
    },
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Standardisation helpers

# COMMAND ----------

def standardise_dates(df: DataFrame, date_cols: list) -> DataFrame:
    """Parses YYYY-MM-DD or DD/MM/YYYY into a real date column; unparseable/missing values
    become null and flow through to Notebook 2's MISSING_* checks rather than being dropped."""
    for col_name in date_cols:
        df = df.withColumn(
            col_name,
            F.coalesce(F.to_date(col_name, "yyyy-MM-dd"), F.to_date(col_name, "dd/MM/yyyy")),
        )
    return df


def standardise_numerics(df: DataFrame, numeric_cols: list) -> DataFrame:
    for col_name in numeric_cols:
        df = df.withColumn(col_name, F.expr(f"try_cast({col_name} as double)"))
    return df


def standardise_currency_code(df: DataFrame, col_name: str) -> DataFrame:
    """Uppercases and trims a plain 3-letter currency code column (accounts.currency,
    loans.currency, transactions.currency) — does not validate against VALID_CURRENCY_CODES,
    that's Notebook 2's job."""
    return df.withColumn(col_name, F.upper(F.trim(F.col(col_name))))


def standardise_currency_pair(df: DataFrame, col_name: str) -> DataFrame:
    """Same XXX/YYY normalisation as the treasury pipeline: a clean 6-letter code with no
    separator gets a slash inserted; anything else (already-valid or genuinely malformed) is
    left for Notebook 2's INVALID_CCY_PAIR-equivalent check to judge."""
    six_letter_no_slash = F.col(col_name).rlike("^[A-Za-z]{6}$")
    inserted_slash = F.concat(F.substring(col_name, 1, 3), F.lit("/"), F.substring(col_name, 4, 3))
    return df.withColumn(
        col_name,
        F.when(six_letter_no_slash, F.upper(inserted_slash)).otherwise(F.upper(F.col(col_name))),
    )


def standardise_month(df: DataFrame, col_name: str) -> DataFrame:
    """capital_positions.month is a YYYY-MM string, not a full date — trim it and leave
    format validation to Notebook 2 (MISSING_MONTH / INVALID_MONTH_FORMAT)."""
    return df.withColumn(col_name, F.trim(F.col(col_name)))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read, standardise, and write each table

# COMMAND ----------

def read_table(table_name: str, cfg: dict) -> DataFrame:
    path = f"{INPUT_DIR}/{cfg['file']}"
    df = spark.read.option("header", True).option("inferSchema", False).csv(path)
    df = standardise_dates(df, cfg["date_cols"])
    df = standardise_numerics(df, cfg["numeric_cols"])
    # Provenance tags on every row: which system, which run, which file. source_country is added
    # separately below, since for a multi-country source it depends on other tables.
    return (
        df.withColumn("source_system", F.lit(SOURCE_SYSTEM))
        .withColumn("ingest_batch_id", F.lit(INGEST_BATCH_ID))
        .withColumn("source_file", F.lit(cfg["file"]))
    )


raw_customers = read_table("customers", TABLES["customers"])

raw_accounts = standardise_currency_code(read_table("accounts", TABLES["accounts"]), "currency")

raw_loans = standardise_currency_code(read_table("loans", TABLES["loans"]), "currency")

raw_transactions = standardise_currency_code(
    read_table("transactions", TABLES["transactions"]), "currency"
)

raw_branches = read_table("branches", TABLES["branches"])

raw_capital_positions = standardise_month(
    read_table("capital_positions", TABLES["capital_positions"]), "month"
)

raw_liquidity_daily = read_table("liquidity_daily", TABLES["liquidity_daily"])

raw_fx_rates = standardise_currency_pair(
    read_table("fx_rates", TABLES["fx_rates"]), "currency_pair"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source tags: country
# MAGIC
# MAGIC A single-country source (the `source_country` parameter is set) stamps that country on every
# MAGIC row. A multi-country source (today's CSV set) takes each row's country from its branch:
# MAGIC branches from their region, customers from their branch, accounts and loans from their
# MAGIC customer, transactions from their account. Bank-wide tables (capital, liquidity, FX) are
# MAGIC `Group`. A row whose branch can't be found is `Unknown` — kept, not dropped: judging broken
# MAGIC links is Notebook 2's job (its orphan checks still flag the row).

# COMMAND ----------

region_to_country = F.create_map([F.lit(x) for pair in REGION_COUNTRY.items() for x in pair])


def one_country_per_key(tagged_df: DataFrame, key_col: str) -> DataFrame:
    """key -> source_country lookup from an already-tagged parent table. Grouped to one row per
    key first: raw data has no primary-key guarantee, and a duplicated parent key would otherwise
    multiply the child rows in the join below."""
    return (
        tagged_df.filter(F.col(key_col).isNotNull())
        .groupBy(key_col)
        .agg(F.first("source_country", ignorenulls=True).alias("source_country"))
        .withColumnRenamed(key_col, "_parent_key")
    )


def with_country_from_parent(child_df: DataFrame, fk_col: str, lookup_df: DataFrame) -> DataFrame:
    """Left join, so every child row survives; no matching parent (or a null key) -> Unknown."""
    return (
        child_df.join(lookup_df, child_df[fk_col] == F.col("_parent_key"), "left")
        .drop("_parent_key")
        .withColumn("source_country", F.coalesce(F.col("source_country"), F.lit("Unknown")))
    )


if SOURCE_COUNTRY:
    (raw_branches, raw_customers, raw_accounts, raw_loans, raw_transactions,
     raw_capital_positions, raw_liquidity_daily, raw_fx_rates) = [
        df.withColumn("source_country", F.lit(SOURCE_COUNTRY))
        for df in (raw_branches, raw_customers, raw_accounts, raw_loans, raw_transactions,
                   raw_capital_positions, raw_liquidity_daily, raw_fx_rates)
    ]
else:
    # Parents first: each table's lookup is built from the one already tagged above it.
    raw_branches = raw_branches.withColumn(
        "source_country", F.coalesce(region_to_country[F.trim(F.col("region"))], F.lit("Unknown"))
    )
    raw_customers = with_country_from_parent(raw_customers, "branch_id", one_country_per_key(raw_branches, "branch_id"))
    customer_countries = one_country_per_key(raw_customers, "customer_id")
    raw_accounts = with_country_from_parent(raw_accounts, "customer_id", customer_countries)
    raw_loans = with_country_from_parent(raw_loans, "customer_id", customer_countries)
    raw_transactions = with_country_from_parent(raw_transactions, "account_id", one_country_per_key(raw_accounts, "account_id"))
    # Bank-wide figures belong to no single branch or country.
    raw_capital_positions = raw_capital_positions.withColumn("source_country", F.lit("Group"))
    raw_liquidity_daily = raw_liquidity_daily.withColumn("source_country", F.lit("Group"))
    raw_fx_rates = raw_fx_rates.withColumn("source_country", F.lit("Group"))

# COMMAND ----------

OUTPUT_TABLES = {
    "raw_customers": raw_customers,
    "raw_accounts": raw_accounts,
    "raw_loans": raw_loans,
    "raw_transactions": raw_transactions,
    "raw_branches": raw_branches,
    "raw_capital_positions": raw_capital_positions,
    "raw_liquidity_daily": raw_liquidity_daily,
    "raw_fx_rates": raw_fx_rates,
}

for table_name, df in OUTPUT_TABLES.items():
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table_name)
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"ingest_batch_id: {INGEST_BATCH_ID}")
for table_name in OUTPUT_TABLES:
    print(f"{table_name}: {spark.table(table_name).count()} rows")

# Rows per source + country: each table's counts here should add up to its total above (the
# country lookups never drop or multiply rows), with Unknown only where a parent key is broken.
for table_name in OUTPUT_TABLES:
    print(table_name)
    spark.table(table_name).groupBy("source_system", "source_country").count().show(truncate=False)