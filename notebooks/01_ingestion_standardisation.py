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

# COMMAND ----------



# COMMAND ----------

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

dbutils.widgets.text("input_dir", "/Volumes/bank_poc/raw", "Input directory")

INPUT_DIR = dbutils.widgets.get("input_dir")

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
    return df


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

for table_name in OUTPUT_TABLES:
    print(f"{table_name}: {spark.table(table_name).count()} rows")