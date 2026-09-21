# Databricks notebook source
# MAGIC %md
# MAGIC # Notebook 3: Nightly KPI Summary
# MAGIC
# MAGIC Precomputes the 8 Executive Summary (Screen 1) KPIs into one row per day in
# MAGIC `kpi_daily_summary`, per `specs/notebook-03-kpi-summary.md`. Reads Notebook 2's `{table}_clean`
# MAGIC output only — never `raw_*`, since those haven't passed the quality gate.
# MAGIC
# MAGIC 3 of the 8 KPIs (NIM, Cost-to-Income, ROE) hit genuine schema gaps and are computed via
# MAGIC explicit, documented placeholder assumptions (spec section 6) rather than left null — the
# MAGIC `assumptions_applied` output column is what lets the UI flag those tiles as demo
# MAGIC assumptions, not verified accounting.
# MAGIC
# MAGIC Currency conversion uses `fx_utils.get_live_rate()` (live API call, logged to
# MAGIC `fx_rate_usage_log`) per `specs/fx-realtime-ingestion.md` — **not** a `fx_rates_clean`
# MAGIC table lookup, which is what the original version of this notebook's spec assumed before
# MAGIC that spec was corrected.
# MAGIC
# MAGIC Input: `capital_positions_clean`, `liquidity_daily_clean`, `loans_clean`, `accounts_clean`,
# MAGIC `branches_clean`, `customers_clean`, `transactions_clean`
# MAGIC Output: Delta table `kpi_daily_summary` (one row per `calculation_date`, idempotent overwrite)

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (catalog `bank_poc` was created in the UI, since Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG bank_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

# MAGIC %run ./fx_utils

# COMMAND ----------

import uuid
from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC Placeholder assumptions from spec section 6 — **not verified accounting, confirm with the
# MAGIC source-of-truth doc's owner before this goes near production.**

# COMMAND ----------

DEPOSIT_RATE_BY_TYPE = {"Current": 0.0, "Savings": 1.5, "Term deposit": 3.0}  # percent
REGION_CURRENCY = {"Beirut": "USD", "North": "USD", "South": "USD", "KSA": "SAR", "Qatar": "QAR"}
NPL_DAYS_PAST_DUE_THRESHOLD = 90

NOTEBOOK_RUN_ID = str(uuid.uuid4())
CALCULATION_DATE = F.current_date()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load clean tables

# COMMAND ----------

capital_positions_clean = spark.table("capital_positions_clean")
liquidity_daily_clean = spark.table("liquidity_daily_clean")
loans_clean = spark.table("loans_clean")
accounts_clean = spark.table("accounts_clean")
branches_clean = spark.table("branches_clean")
customers_clean = spark.table("customers_clean")
transactions_clean = spark.table("transactions_clean")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Live currency conversion
# MAGIC
# MAGIC One `get_live_rate` call per distinct currency actually present in the data (not per row) —
# MAGIC collected on the driver, then applied as a broadcast map. `used_in_calculation` labels each
# MAGIC fetch in `fx_rate_usage_log` so an auditor can see which KPI a given rate fed.

# COMMAND ----------

def usd_rate_map(currencies: list, used_in_calculation: str) -> dict:
    rates = {"USD": 1.0}
    for ccy in currencies:
        if ccy is None or ccy == "USD" or ccy in rates:
            continue
        rates[ccy] = get_live_rate_and_log(f"USD/{ccy}", NOTEBOOK_RUN_ID, used_in_calculation)
    return rates


def to_usd(df, amount_col: str, currency_col: str, rate_map: dict, out_col: str = None):
    out_col = out_col or amount_col
    mapping_expr = F.create_map([F.lit(x) for pair in rate_map.items() for x in pair])
    return df.withColumn(out_col, F.col(amount_col) / mapping_expr[F.col(currency_col)])

# COMMAND ----------

loan_currencies = [r.currency for r in loans_clean.select("currency").distinct().collect()]
account_currencies = [r.currency for r in accounts_clean.select("currency").distinct().collect()]
txn_currencies = [r.currency for r in transactions_clean.select("currency").distinct().collect()]

loan_rates = usd_rate_map(loan_currencies, "loans_conversion")
account_rates = usd_rate_map(account_currencies, "accounts_conversion")
txn_rates = usd_rate_map(txn_currencies, "transactions_conversion")
region_rates = usd_rate_map(list(set(REGION_CURRENCY.values())), "branch_opex_conversion")

loans_usd = to_usd(loans_clean, "outstanding", "currency", loan_rates, "outstanding_usd")
accounts_usd = to_usd(accounts_clean, "balance", "currency", account_rates, "balance_usd")
transactions_usd = to_usd(transactions_clean, "amount", "currency", txn_rates, "amount_usd")

# COMMAND ----------

# MAGIC %md
# MAGIC ## The 5 directly-computable KPIs (spec section 5)

# COMMAND ----------

latest_capital = capital_positions_clean.orderBy(F.col("month").desc()).limit(1).collect()[0]
car_pct = (latest_capital["tier1_capital"] + latest_capital["tier2_capital"]) / latest_capital["risk_weighted_assets"] * 100

latest_liquidity = liquidity_daily_clean.orderBy(F.col("date").desc()).limit(1).collect()[0]
lcr_pct = latest_liquidity["hqla"] / latest_liquidity["net_outflows_30d"] * 100

loans_agg = loans_usd.agg(
    F.sum("outstanding_usd").alias("total_outstanding_usd"),
    F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)).alias("npl_outstanding_usd"),
).collect()[0]
npl_ratio_pct = loans_agg["npl_outstanding_usd"] / loans_agg["total_outstanding_usd"] * 100

accounts_agg = accounts_usd.agg(
    F.sum("balance_usd").alias("total_balance_usd"),
    F.sum(F.when(F.col("currency") != "LBP", F.col("balance_usd")).otherwise(0)).alias("non_lbp_balance_usd"),
).collect()[0]

total_assets_usd = loans_agg["total_outstanding_usd"] + accounts_agg["total_balance_usd"]
dollarization_ratio_pct = accounts_agg["non_lbp_balance_usd"] / accounts_agg["total_balance_usd"] * 100

# COMMAND ----------

# MAGIC %md
# MAGIC ## NIM (placeholder: `DEPOSIT_RATE_BY_TYPE`)

# COMMAND ----------

interest_income_usd = loans_usd.agg(
    F.sum(F.col("outstanding_usd") * F.col("interest_rate") / 100).alias("v")
).collect()[0]["v"]

deposit_rate_map_expr = F.create_map([F.lit(x) for pair in DEPOSIT_RATE_BY_TYPE.items() for x in pair])
interest_expense_usd = accounts_usd.withColumn(
    "deposit_rate", deposit_rate_map_expr[F.col("type")]
).agg(
    F.sum(F.col("balance_usd") * F.col("deposit_rate") / 100).alias("v")
).collect()[0]["v"]

nim_pct = (interest_income_usd - interest_expense_usd) / loans_agg["total_outstanding_usd"] * 100

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cost-to-Income and ROE (placeholders: `REGION_CURRENCY`, `tier1_capital`-as-equity)

# COMMAND ----------

region_rate_map_expr = F.create_map([F.lit(x) for pair in region_rates.items() for x in pair])
branch_currency_map_expr = F.create_map([F.lit(x) for pair in REGION_CURRENCY.items() for x in pair])

branches_opex_usd = branches_clean.withColumn(
    "opex_currency", branch_currency_map_expr[F.col("region")]
).withColumn(
    "opex_usd", F.col("monthly_opex") / region_rate_map_expr[F.col("opex_currency")]
)
total_opex_usd = branches_opex_usd.agg(F.sum("opex_usd").alias("v")).collect()[0]["v"]

fee_income_usd = transactions_usd.filter(F.col("type") == "Fee").agg(
    F.sum("amount_usd").alias("v")
).collect()[0]["v"] or 0.0

revenue_usd = interest_income_usd + fee_income_usd
cost_to_income_pct = total_opex_usd / revenue_usd * 100

profit_usd = revenue_usd - total_opex_usd
roe_pct = profit_usd / latest_capital["tier1_capital"] * 100

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble and write (idempotent per-day overwrite)
# MAGIC
# MAGIC Reads any existing `kpi_daily_summary`, drops today's row if it already exists, unions in
# MAGIC the freshly-computed one, and overwrites — this is what makes rerunning the notebook on the
# MAGIC same day replace today's numbers instead of appending a duplicate (spec section 8).

# COMMAND ----------

ASSUMPTIONS_APPLIED = [
    "DEPOSIT_RATE_BY_TYPE placeholder (nim_pct)",
    "REGION_CURRENCY placeholder (cost_to_income_pct, roe_pct)",
    "tier1_capital-as-equity proxy (roe_pct)",
]

new_row = spark.createDataFrame([{
    "calculation_date": None,  # set below via withColumn so it's a real `date`, not a Python str
    "car_pct": float(car_pct),
    "lcr_pct": float(lcr_pct),
    "npl_ratio_pct": float(npl_ratio_pct),
    "total_assets_usd": float(total_assets_usd),
    "dollarization_ratio_pct": float(dollarization_ratio_pct),
    "nim_pct": float(nim_pct),
    "cost_to_income_pct": float(cost_to_income_pct),
    "roe_pct": float(roe_pct),
}]).withColumn("calculation_date", CALCULATION_DATE).withColumn(
    "assumptions_applied", F.array([F.lit(a) for a in ASSUMPTIONS_APPLIED])
)

if spark.catalog.tableExists("kpi_daily_summary"):
    existing = spark.table("kpi_daily_summary").filter(F.col("calculation_date") != CALCULATION_DATE)
    kpi_daily_summary = existing.unionByName(new_row)
else:
    kpi_daily_summary = new_row

(
    kpi_daily_summary.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable("kpi_daily_summary")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

display(spark.table("kpi_daily_summary").orderBy(F.col("calculation_date").desc()))
print(f"fx_rate_usage_log rows logged this run: check notebook_run_id = '{NOTEBOOK_RUN_ID}'")
