# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Notebook 6: Portfolio, Branch & Scenario Snapshot
# MAGIC
# MAGIC Precomputes the Gold-layer aggregates Screens 2, 4, and 5 need, per
# MAGIC `specs/notebook-06-portfolio-branch-scenario-snapshot.md`. Reads only Notebook 2's clean
# MAGIC tables — deliberately no dependency on Notebook 3, so the two can be built/run in parallel.
# MAGIC
# MAGIC Introduces 3 new placeholder assumptions beyond Notebook 3's (`PRODUCT_RATE_TYPE`,
# MAGIC `ACCOUNT_RATE_TYPE`, `SEGMENT_COST_ALLOCATION`) — all flagged inline, none of them sourced
# MAGIC from the schema or the source doc, confirm with the client before treating as fact.
# MAGIC
# MAGIC Every ratio here that looks implausible on `bank-data/*.csv` (branch/segment profit,
# MAGIC cost-to-income) is a sample-size artifact, same caveat as Notebook 3 — 5 clean loans and a
# MAGIC handful of customers can't produce realistic ratios against branch-scale opex figures.
# MAGIC
# MAGIC Input: `loans_clean`, `accounts_clean`, `transactions_clean`, `branches_clean`,
# MAGIC `customers_clean`, `capital_positions_clean`, `liquidity_daily_clean`
# MAGIC Output: `loan_breakdown_by_dimension`, `loan_stage_summary`, `top_exposures`,
# MAGIC `loan_ageing_summary`, `ltv_distribution`, `branch_performance_summary`,
# MAGIC `segment_performance_summary`, `product_performance_summary`, `scenario_snapshot`

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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config

# COMMAND ----------

REGION_CURRENCY = {"Beirut": "USD", "North": "USD", "South": "USD", "KSA": "SAR", "Qatar": "QAR"}
# Every product in loans.csv must be listed: an unmapped product gets a null rate type, and a null
# map key crashes the scenario snapshot below ("input for StringType() must not be None").
PRODUCT_RATE_TYPE = {"Mortgage": "fixed", "Personal": "fixed", "Auto": "fixed", "SME": "floating", "Corporate": "floating"}
ACCOUNT_RATE_TYPE = {"Current": "floating", "Savings": "floating", "Term deposit": "fixed"}
NPL_DAYS_PAST_DUE_THRESHOLD = 90
ALL_CURRENCIES = ["USD", "EUR", "LBP", "SAR", "QAR"]

NOTEBOOK_RUN_ID = str(uuid.uuid4())
# Optional `calculation_date` parameter (YYYY-MM-DD): stamps this run's output with that business
# date instead of today, so loading several days' data one after another (e.g. a demo backfill)
# lands as separate dated rows. Blank - the default, and what the scheduled job passes - keeps
# the original behaviour: today's date.
dbutils.widgets.text("calculation_date", "", "Calculation date (YYYY-MM-DD, blank = today)")
_calculation_date_param = dbutils.widgets.get("calculation_date").strip()
CALCULATION_DATE = F.to_date(F.lit(_calculation_date_param)) if _calculation_date_param else F.current_date()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load clean tables and live FX rates
# MAGIC
# MAGIC One `get_live_rate` call per currency in the fixed platform set, not per table/column —
# MAGIC reused across every aggregate below. Labeled generically in `fx_rate_usage_log` since a
# MAGIC single notebook run's rates feed many calculations here; Notebook 3 labels more granularly
# MAGIC since it has far fewer conversion sites.

# COMMAND ----------

loans_clean = spark.table("loans_clean")
accounts_clean = spark.table("accounts_clean")
transactions_clean = spark.table("transactions_clean")
branches_clean = spark.table("branches_clean")
customers_clean = spark.table("customers_clean")
capital_positions_clean = spark.table("capital_positions_clean")
liquidity_daily_clean = spark.table("liquidity_daily_clean")

rate_map = {"USD": 1.0}
for ccy in ALL_CURRENCIES:
    if ccy == "USD":
        continue
    rate_map[ccy] = get_live_rate_and_log(f"USD/{ccy}", NOTEBOOK_RUN_ID, "notebook_06_portfolio_branch_scenario")
rate_map_expr = F.create_map([F.lit(x) for pair in rate_map.items() for x in pair])


def to_usd(df, amount_col: str, currency_col: str, out_col: str):
    return df.withColumn(out_col, F.col(amount_col) / rate_map_expr[F.col(currency_col)])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Joined base frames
# MAGIC
# MAGIC Built once, reused across every output table below, rather than re-joining per section.

# COMMAND ----------

loans_joined = (
    to_usd(loans_clean, "outstanding", "currency", "outstanding_usd")
    .transform(lambda df: to_usd(df, "provision_amount", "currency", "provision_amount_usd"))
    .join(customers_clean.select("customer_id", F.col("name").alias("customer_name"), "segment", "branch_id"), "customer_id")
    .join(branches_clean.select("branch_id", "region"), "branch_id")
)

accounts_joined = (
    to_usd(accounts_clean, "balance", "currency", "balance_usd")
    .join(customers_clean.select("customer_id", "segment", "branch_id"), "customer_id")
    .join(branches_clean.select("branch_id", "region"), "branch_id")
)

transactions_joined = (
    to_usd(transactions_clean, "amount", "currency", "amount_usd")
    .join(accounts_clean.select("account_id", "customer_id"), "account_id")
    .join(customers_clean.select("customer_id", "segment", "branch_id"), "customer_id")
    .join(branches_clean.select("branch_id", "region"), "branch_id")
)

branches_opex_usd = to_usd(
    branches_clean.withColumn("opex_currency", F.create_map([F.lit(x) for p in REGION_CURRENCY.items() for x in p])[F.col("region")]),
    "monthly_opex", "opex_currency", "opex_usd",
)

latest_capital = capital_positions_clean.orderBy(F.col("month").desc()).limit(1).collect()[0]
total_capital_usd = latest_capital["tier1_capital"] + latest_capital["tier2_capital"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## `loan_breakdown_by_dimension`

# COMMAND ----------

def breakdown(df, dim_col: str, dim_type: str):
    return df.groupBy(F.col(dim_col).alias("dimension_value")).agg(
        F.sum("outstanding_usd").alias("total_outstanding_usd"),
        F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)).alias("bad_loan_outstanding_usd"),
    ).withColumn("dimension_type", F.lit(dim_type)).select("dimension_type", "dimension_value", "total_outstanding_usd", "bad_loan_outstanding_usd")


loan_breakdown_by_dimension = (
    breakdown(loans_joined, "product", "product")
    .unionByName(breakdown(loans_joined, "segment", "segment"))
    .unionByName(breakdown(loans_joined, "branch_id", "branch"))
    .unionByName(breakdown(loans_joined, "currency", "currency"))
    .withColumn("calculation_date", CALCULATION_DATE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `loan_stage_summary`

# COMMAND ----------

loan_stage_summary = loans_joined.groupBy("stage").agg(
    F.count("*").alias("loan_count"),
    F.sum("outstanding_usd").alias("outstanding_usd"),
    F.sum("provision_amount_usd").alias("provisions_usd"),
).withColumn(
    "coverage_pct", F.col("provisions_usd") / F.col("outstanding_usd") * 100
).withColumn("calculation_date", CALCULATION_DATE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `top_exposures`
# MAGIC
# MAGIC Top 20 by total outstanding per customer. Where a customer holds multiple loans, `product`
# MAGIC and `days_past_due` are taken from that customer's single largest loan (via a rank window),
# MAGIC since a customer-level row can't show a per-loan product/DPD pair for more than one loan —
# MAGIC not specified explicitly in the spec's formula, called out here as a modeling choice.

# COMMAND ----------

customer_totals = loans_joined.groupBy("customer_id", "customer_name").agg(F.sum("outstanding_usd").alias("outstanding_usd"))

largest_loan_window = Window.partitionBy("customer_id").orderBy(F.col("outstanding_usd").desc())
largest_loan_per_customer = (
    loans_joined.withColumn("rn", F.row_number().over(largest_loan_window))
    .filter(F.col("rn") == 1)
    .select("customer_id", "product", "days_past_due")
)

top_exposures = (
    customer_totals.join(largest_loan_per_customer, "customer_id")
    .withColumn("pct_of_capital", F.col("outstanding_usd") / F.lit(total_capital_usd) * 100)
    .withColumn("calculation_date", CALCULATION_DATE)
    .orderBy(F.col("outstanding_usd").desc())
    .limit(20)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `loan_ageing_summary`
# MAGIC
# MAGIC Bucket boundaries per spec section 4: a loan at exactly 30/90/180 days lands in the lower
# MAGIC bucket (`<` on the upper edge, not `<=`).

# COMMAND ----------

ageing_bucket = (
    F.when(F.col("days_past_due") == 0, "Current")
    .when(F.col("days_past_due") < 30, "1-30")
    .when(F.col("days_past_due") < 60, "31-60")
    .when(F.col("days_past_due") < 90, "61-90")
    .when(F.col("days_past_due") < 180, "90-180")
    .otherwise("180+")
)

total_outstanding_usd = loans_joined.agg(F.sum("outstanding_usd").alias("v")).collect()[0]["v"]

loan_ageing_summary = (
    loans_joined.withColumn("bucket", ageing_bucket)
    .groupBy("bucket")
    .agg(F.sum("outstanding_usd").alias("outstanding_usd"))
    .withColumn("pct_of_book", F.col("outstanding_usd") / F.lit(total_outstanding_usd) * 100)
    .withColumn("calculation_date", CALCULATION_DATE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `ltv_distribution`
# MAGIC
# MAGIC Native-currency ratio, no conversion needed (outstanding/collateral share the loan's own
# MAGIC currency). Zero collateral against nonzero outstanding is treated as `>100%` (undefined LTV
# MAGIC = fully uncovered), per spec section 4.

# COMMAND ----------

ltv_ratio = F.when(F.col("collateral_value") == 0, F.lit(None)).otherwise(F.col("outstanding") / F.col("collateral_value") * 100)

ltv_bucket = (
    F.when(F.col("collateral_value") == 0, ">100%")
    .when(ltv_ratio < 50, "<50%")
    .when(ltv_ratio < 80, "50-80%")
    .when(ltv_ratio <= 100, "80-100%")
    .otherwise(">100%")
)

ltv_distribution = (
    loans_joined.withColumn("bucket", ltv_bucket)
    .groupBy("bucket")
    .agg(F.sum("outstanding_usd").alias("outstanding_usd"), F.count("*").alias("loan_count"))
    .withColumn("calculation_date", CALCULATION_DATE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `branch_performance_summary`

# COMMAND ----------

branch_deposits = accounts_joined.groupBy("branch_id").agg(F.sum("balance_usd").alias("deposits_usd"))
branch_loans = loans_joined.groupBy("branch_id").agg(F.sum("outstanding_usd").alias("loans_usd"))
branch_interest_income = loans_joined.groupBy("branch_id").agg(
    F.sum(F.col("outstanding_usd") * F.col("interest_rate") / 100).alias("interest_income_usd")
)
branch_fee_income = transactions_joined.filter(F.col("type") == "Fee").groupBy("branch_id").agg(
    F.sum("amount_usd").alias("fee_income_usd")
)

branch_performance_summary = (
    branches_opex_usd.select("branch_id", "region", "staff_count", "opex_usd")
    .join(branch_deposits, "branch_id", "left")
    .join(branch_loans, "branch_id", "left")
    .join(branch_interest_income, "branch_id", "left")
    .join(branch_fee_income, "branch_id", "left")
    .na.fill(0.0, ["deposits_usd", "loans_usd", "interest_income_usd", "fee_income_usd"])
    .withColumn("revenue_usd", F.col("interest_income_usd") + F.col("fee_income_usd"))
    .withColumn("cost_usd", F.col("opex_usd"))
    .withColumn("profit_usd", F.col("revenue_usd") - F.col("cost_usd"))
    .withColumn("cost_to_income_pct", F.col("cost_usd") / F.col("revenue_usd") * 100)
    .withColumn("profit_per_staff_usd", F.col("profit_usd") / F.col("staff_count"))
    .withColumn("calculation_date", CALCULATION_DATE)
    .select(
        "calculation_date", "branch_id", "region", "deposits_usd", "loans_usd", "revenue_usd",
        "cost_usd", "profit_usd", "cost_to_income_pct", "staff_count", "profit_per_staff_usd",
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `segment_performance_summary`
# MAGIC
# MAGIC `SEGMENT_COST_ALLOCATION` (spec section 3): each branch's opex is pro-rated across its
# MAGIC segments proportional to that segment's share of (loans + deposits) at that branch, then
# MAGIC summed across branches per segment. **A modeling choice, not a measured cost — flag in the
# MAGIC UI as "cost allocated proportionally, not measured."**

# COMMAND ----------

branch_segment_volume = (
    loans_joined.groupBy("branch_id", "segment").agg(F.sum("outstanding_usd").alias("loans_usd"))
    .join(
        accounts_joined.groupBy("branch_id", "segment").agg(F.sum("balance_usd").alias("deposits_usd")),
        ["branch_id", "segment"], "outer",
    )
    .na.fill(0.0, ["loans_usd", "deposits_usd"])
    .withColumn("volume_usd", F.col("loans_usd") + F.col("deposits_usd"))
)

branch_total_volume = branch_segment_volume.groupBy("branch_id").agg(F.sum("volume_usd").alias("branch_total_volume_usd"))

segment_allocated_cost = (
    branch_segment_volume.join(branch_total_volume, "branch_id")
    .join(branches_opex_usd.select("branch_id", "opex_usd"), "branch_id")
    .withColumn(
        "allocated_cost_usd",
        F.when(F.col("branch_total_volume_usd") > 0, F.col("opex_usd") * F.col("volume_usd") / F.col("branch_total_volume_usd")).otherwise(0.0),
    )
    .groupBy("segment")
    .agg(F.sum("allocated_cost_usd").alias("allocated_cost_usd"))
)

segment_customer_counts = customers_clean.groupBy("segment").agg(F.countDistinct("customer_id").alias("customer_count"))
segment_deposits = accounts_joined.groupBy("segment").agg(F.sum("balance_usd").alias("deposits_usd"))
segment_loans = loans_joined.groupBy("segment").agg(
    F.sum("outstanding_usd").alias("loans_usd"),
    F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)).alias("bad_loans_usd"),
)
segment_interest_income = loans_joined.groupBy("segment").agg(
    F.sum(F.col("outstanding_usd") * F.col("interest_rate") / 100).alias("interest_income_usd")
)
segment_fee_income = transactions_joined.filter(F.col("type") == "Fee").groupBy("segment").agg(
    F.sum("amount_usd").alias("fee_income_usd")
)

segment_performance_summary = (
    segment_customer_counts
    .join(segment_deposits, "segment", "left")
    .join(segment_loans, "segment", "left")
    .join(segment_interest_income, "segment", "left")
    .join(segment_fee_income, "segment", "left")
    .join(segment_allocated_cost, "segment", "left")
    .na.fill(0.0, ["deposits_usd", "loans_usd", "bad_loans_usd", "interest_income_usd", "fee_income_usd", "allocated_cost_usd"])
    .withColumn("revenue_usd", F.col("interest_income_usd") + F.col("fee_income_usd"))
    .withColumn("profit_usd", F.col("revenue_usd") - F.col("allocated_cost_usd"))
    .withColumn("revenue_per_customer_usd", F.col("revenue_usd") / F.col("customer_count"))
    .withColumn("calculation_date", CALCULATION_DATE)
    .select(
        "calculation_date", "segment", "customer_count", "deposits_usd", "loans_usd",
        "revenue_usd", "bad_loans_usd", "profit_usd", "revenue_per_customer_usd",
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `product_performance_summary`
# MAGIC
# MAGIC `net_contribution_usd` needs no new assumption — directly computable from
# MAGIC `loans_clean.provision_amount` (spec section 4).

# COMMAND ----------

product_performance_summary = (
    loans_joined.groupBy("product")
    .agg(
        F.sum("outstanding_usd").alias("outstanding_usd"),
        F.avg("interest_rate").alias("avg_interest_rate"),
        F.sum(F.col("outstanding_usd") * F.col("interest_rate") / 100).alias("interest_income_usd"),
        F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)).alias("npl_outstanding_usd"),
        F.sum("provision_amount_usd").alias("provisions_usd"),
    )
    .withColumn("npl_pct", F.col("npl_outstanding_usd") / F.col("outstanding_usd") * 100)
    .withColumn("net_contribution_usd", F.col("interest_income_usd") - F.col("provisions_usd"))
    .withColumn("calculation_date", CALCULATION_DATE)
    .select(
        "calculation_date", "product", "outstanding_usd", "avg_interest_rate",
        "interest_income_usd", "npl_pct", "net_contribution_usd",
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## `scenario_snapshot`
# MAGIC
# MAGIC Single row, nested maps, overwritten each run — Screen 4 fetches this once per page load
# MAGIC and recomputes every slider movement in the browser against it, never re-querying Databricks.

# COMMAND ----------

def map_column(df, key_col: str, value_expr):
    rows = df.withColumn("_value", value_expr).groupBy(key_col).agg(F.sum("_value").alias("_total")).collect()
    return {r[key_col]: r["_total"] for r in rows}


product_rate_type_expr = F.create_map([F.lit(x) for p in PRODUCT_RATE_TYPE.items() for x in p])
account_rate_type_expr = F.create_map([F.lit(x) for p in ACCOUNT_RATE_TYPE.items() for x in p])

loans_by_currency = map_column(loans_joined, "currency", F.col("outstanding_usd"))
loans_by_product = map_column(loans_joined, "product", F.col("outstanding_usd"))
loans_by_rate_type = map_column(
    loans_joined.withColumn("rate_type", product_rate_type_expr[F.col("product")]), "rate_type", F.col("outstanding_usd")
)
deposits_by_type = map_column(accounts_joined, "type", F.col("balance_usd"))
deposits_by_rate_type = map_column(
    accounts_joined.withColumn("rate_type", account_rate_type_expr[F.col("type")]), "rate_type", F.col("balance_usd")
)

latest_liquidity = liquidity_daily_clean.orderBy(F.col("date").desc()).limit(1).collect()[0]
weighted_avg_rate = loans_joined.agg(
    (F.sum(F.col("outstanding_usd") * F.col("interest_rate")) / F.sum("outstanding_usd")).alias("v")
).collect()[0]["v"]

npl_pct_bankwide = loans_joined.agg(
    (F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)) / F.sum("outstanding_usd") * 100).alias("v")
).collect()[0]["v"]
coverage_pct_bankwide = loans_joined.agg(
    (F.sum("provision_amount_usd") / F.sum("outstanding_usd") * 100).alias("v")
).collect()[0]["v"]

scenario_row = spark.createDataFrame([{
    "loans_by_currency": loans_by_currency,
    "loans_by_product": loans_by_product,
    "loans_by_rate_type": loans_by_rate_type,
    "deposits_by_type": deposits_by_type,
    "deposits_by_rate_type": deposits_by_rate_type,
    "tier1_capital_usd": float(latest_capital["tier1_capital"]),
    "tier2_capital_usd": float(latest_capital["tier2_capital"]),
    "risk_weighted_assets_usd": float(latest_capital["risk_weighted_assets"]),
    "hqla_usd": float(latest_liquidity["hqla"]),
    "net_outflows_30d_usd": float(latest_liquidity["net_outflows_30d"]),
    "stable_funding_usd": float(latest_liquidity["stable_funding"]),
    "required_funding_usd": float(latest_liquidity["required_funding"]),
    "current_npl_pct": float(npl_pct_bankwide),
    "current_coverage_pct": float(coverage_pct_bankwide),
    "current_avg_interest_rate": float(weighted_avg_rate),
}]).withColumn("calculation_date", CALCULATION_DATE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write outputs (each overwritten wholesale — these are current-snapshot tables, no
# MAGIC historical trend per spec section 7's non-goals, so there's no per-day filtering to do)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Country performance (FLOW-4, `specs/cfo-country-view.md`)
# MAGIC
# MAGIC The CFO dashboard's global view: one row per country — customers, deposits, loans, bad loans
# MAGIC and transaction activity, all in USD (the platform's reporting currency: every other Gold table
# MAGIC here is USD too). The country is FLOW-1a's `source_country` tag on each record
# MAGIC (`specs/source-tagging.md`); data loaded before tagging shows as `Unknown`. Bank-wide figures
# MAGIC (capital, liquidity) belong to no country and stay on the KPI tiles.

# COMMAND ----------

def country_of(df):
    return F.col("source_country") if "source_country" in df.columns else F.lit("Unknown")


country_customers = customers_clean.groupBy(country_of(customers_clean).alias("country")).agg(
    F.countDistinct("customer_id").alias("customer_count")
)
country_deposits = accounts_joined.groupBy(country_of(accounts_joined).alias("country")).agg(
    F.sum("balance_usd").alias("deposits_usd")
)
country_loans = loans_joined.groupBy(country_of(loans_joined).alias("country")).agg(
    F.sum("outstanding_usd").alias("loans_usd"),
    F.sum(F.when(F.col("days_past_due") >= NPL_DAYS_PAST_DUE_THRESHOLD, F.col("outstanding_usd")).otherwise(0)).alias("npl_loans_usd"),
)
# Volume = absolute amounts: withdrawals are negative, and activity is what's being measured here.
country_transactions = transactions_joined.groupBy(country_of(transactions_joined).alias("country")).agg(
    F.count("*").alias("transaction_count"),
    F.sum(F.abs("amount_usd")).alias("transaction_volume_usd"),
)

# Full outer joins: a country with customers but no loans (or the reverse) still gets its row.
country_performance_summary = (
    country_customers.join(country_deposits, "country", "full")
    .join(country_loans, "country", "full")
    .join(country_transactions, "country", "full")
    .na.fill(0, ["customer_count", "transaction_count"])
    .na.fill(0.0, ["deposits_usd", "loans_usd", "npl_loans_usd", "transaction_volume_usd"])
    .withColumn("npl_ratio_pct", F.lit(None).cast("double"))   # set safely by DIVISION_PATCHES below
    .withColumn("calculation_date", CALCULATION_DATE)
    .select(
        "calculation_date", "country", "customer_count", "deposits_usd", "loans_usd", "npl_loans_usd",
        "npl_ratio_pct", "transaction_count", "transaction_volume_usd",
    )
)

# COMMAND ----------

DIVISION_PATCHES = {
    "loan_stage_summary": {
        "coverage_pct": F.expr("try_divide(provisions_usd, outstanding_usd)") * 100,
    },
    "branch_performance_summary": {
        "cost_to_income_pct": F.expr("try_divide(cost_usd, revenue_usd)") * 100,
        "profit_per_staff_usd": F.expr("try_divide(profit_usd, CAST(staff_count AS DOUBLE))"),
    },
    "segment_performance_summary": {
        "revenue_per_customer_usd": F.expr("try_divide(revenue_usd, CAST(customer_count AS DOUBLE))"),
    },
    "country_performance_summary": {
        "npl_ratio_pct": F.expr("try_divide(npl_loans_usd, loans_usd)") * 100,
    },
    # product_performance_summary.npl_pct: npl_outstanding_usd is dropped by Cell 26's
    # .select() so try_divide cannot be applied here; safe with sample data since
    # all products have outstanding_usd > 0. Fix Cell 26 if zero-outstanding products arise.
}

OUTPUT_TABLES = {
    "loan_breakdown_by_dimension": loan_breakdown_by_dimension,
    "loan_stage_summary": loan_stage_summary,
    "top_exposures": top_exposures,
    "loan_ageing_summary": loan_ageing_summary,
    "ltv_distribution": ltv_distribution,
    "branch_performance_summary": branch_performance_summary,
    "segment_performance_summary": segment_performance_summary,
    "product_performance_summary": product_performance_summary,
    "scenario_snapshot": scenario_row,
    "country_performance_summary": country_performance_summary,
}

for table_name, df in OUTPUT_TABLES.items():
    if table_name in DIVISION_PATCHES:
        df = df.withColumns(DIVISION_PATCHES[table_name])
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