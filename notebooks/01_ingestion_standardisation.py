# Databricks notebook source
# MAGIC %md
# MAGIC # Notebook 1: Ingestion & Standardisation
# MAGIC
# MAGIC Reads the three raw entity position files (Lebanon, KSA, Qatar), standardises them
# MAGIC to one common schema (column names, date format, currency-pair notation, USD-equivalent
# MAGIC amounts), and writes the unified result to the Delta table `treasury_positions_raw`.
# MAGIC
# MAGIC Input: `lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv`
# MAGIC Output: Delta table `treasury_positions_raw`

# COMMAND ----------

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC File locations and the two lookup tables that drive standardisation:
# MAGIC - `ENTITY_HOME_CURRENCY`: the currency each entity's source amounts are already denominated in
# MAGIC   (per the POC brief — Lebanon reports in USD, KSA in SAR, Qatar in QAR). This tells us which
# MAGIC   FX rate to apply, independent of whatever the `currency_pair` column says (that column can be
# MAGIC   malformed and is verified separately in Notebook 2).
# MAGIC - `FX_RATE_TO_USD`: hardcoded POC rates (units of USD per 1 unit of the local currency). No live
# MAGIC   feed is used for this POC, per the brief.

# COMMAND ----------

# dbutils.widgets can override these paths per-environment; default to the repo root for local/demo runs.
dbutils.widgets.text("input_dir", "/Volumes/treasury_poc/raw", "Input directory")
dbutils.widgets.text("output_table", "treasury_positions_raw", "Output Delta table name")

INPUT_DIR = dbutils.widgets.get("input_dir")
OUTPUT_TABLE = dbutils.widgets.get("output_table")

SOURCE_FILES = {
    "LEB": f"{INPUT_DIR}/lebanon_positions.csv",
    "KSA": f"{INPUT_DIR}/ksa_positions.csv",
    "QAT": f"{INPUT_DIR}/qatar_positions.csv",
}

ENTITY_HOME_CURRENCY = {
    "LEB": "USD",
    "KSA": "SAR",
    "QAT": "QAR",
}

# Hardcoded POC FX table: USD value of 1 unit of the local currency.
FX_RATE_TO_USD = {
    "USD": 1.0,
    "SAR": 0.2667,   # ~3.75 SAR per USD
    "QAR": 0.2747,   # ~3.64 QAR per USD
    "EUR": 1.0900,   # 1 EUR = 1.09 USD
    "LBP": 0.0000112,  # post-2019 parallel-market rate, ~89,500 LBP per USD
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Read each entity file
# MAGIC
# MAGIC Each entity's CSV is read independently because they don't share a schema yet — Qatar
# MAGIC uses `trade_amt` instead of `notional_amount`, and column presence/order can otherwise
# MAGIC differ by entity. `entity_code` is added defensively even though all three sample files
# MAGIC already include it, in case a future source system omits it.

# COMMAND ----------

def read_entity_csv(entity_code: str, path: str) -> DataFrame:
    df = (
        spark.read
        .option("header", True)
        .option("inferSchema", False)  # keep everything as string; we cast explicitly after cleaning
        .csv(path)
    )

    # Qatar's source system names the notional column `trade_amt` — normalise to `notional_amount`.
    if "trade_amt" in df.columns and "notional_amount" not in df.columns:
        df = df.withColumnRenamed("trade_amt", "notional_amount")

    # Defensive: add entity_code if a source file ever omits it.
    if "entity_code" not in df.columns:
        df = df.withColumn("entity_code", F.lit(entity_code))

    return df.withColumn("source_file", F.lit(path.split("/")[-1]))


raw_frames = {code: read_entity_csv(code, path) for code, path in SOURCE_FILES.items()}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Standardise date formats to `YYYY-MM-DD`
# MAGIC
# MAGIC Lebanon and Qatar already use `YYYY-MM-DD`; KSA uses `DD/MM/YYYY`. `to_date` is tried
# MAGIC against both patterns and coalesced, so this handles either format regardless of which
# MAGIC entity it came from. A row with no date at all (or an unparseable one) becomes null here —
# MAGIC Notebook 2's `MISSING_DATE` check catches it downstream; this step does not drop rows.

# COMMAND ----------

def standardise_dates(df: DataFrame) -> DataFrame:
    return df.withColumn(
        "trade_date",
        F.coalesce(
            F.to_date("trade_date", "yyyy-MM-dd"),
            F.to_date("trade_date", "dd/MM/yyyy"),
        ),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Standardise currency-pair notation to `XXX/YYY`
# MAGIC
# MAGIC Some source rows write pairs without a separator (`USDSAR`, `USDQAR`). Where the value is
# MAGIC exactly six letters we insert a `/` after the third character. Anything that isn't a clean
# MAGIC 6-letter or already-slashed code (e.g. `XYZ/USD`, `QR/USD`) is left untouched — those are
# MAGIC genuinely invalid pairs and Notebook 2's `INVALID_CCY_PAIR` check is what's meant to catch
# MAGIC them, not silent reformatting here.

# COMMAND ----------

def standardise_currency_pair(df: DataFrame) -> DataFrame:
    six_letter_no_slash = F.col("currency_pair").rlike("^[A-Za-z]{6}$")
    inserted_slash = F.concat(
        F.substring("currency_pair", 1, 3), F.lit("/"), F.substring("currency_pair", 4, 3)
    )
    return df.withColumn(
        "currency_pair",
        F.when(six_letter_no_slash, F.upper(inserted_slash)).otherwise(F.upper(F.col("currency_pair"))),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Convert amounts to USD equivalent
# MAGIC
# MAGIC Amounts are cast to `double` first (non-numeric text like `"eighty thousand"` or `"n/a"`
# MAGIC becomes null via `try_cast`, which Notebook 2's `INVALID_AMOUNT` check flags) then multiplied
# MAGIC by the entity's home-currency FX rate. Original amounts are kept alongside the USD columns
# MAGIC so downstream checks (e.g. reconciliation tolerance) can still compare like-for-like within
# MAGIC an entity if needed.

# COMMAND ----------

AMOUNT_COLUMNS = ["notional_amount", "base_currency_amount", "counter_currency_amount", "limit_threshold"]


def convert_to_usd(df: DataFrame, entity_code: str) -> DataFrame:
    fx_rate = FX_RATE_TO_USD[ENTITY_HOME_CURRENCY[entity_code]]

    for col_name in AMOUNT_COLUMNS:
        df = df.withColumn(col_name, F.expr(f"try_cast({col_name} as double)"))
        df = df.withColumn(f"{col_name}_usd", F.round(F.col(col_name) * F.lit(fx_rate), 2))

    return df.withColumn("home_currency", F.lit(ENTITY_HOME_CURRENCY[entity_code]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Apply standardisation per entity, then union into one schema

# COMMAND ----------

standardised_frames = []
for entity_code, df in raw_frames.items():
    df = standardise_dates(df)
    df = standardise_currency_pair(df)
    df = convert_to_usd(df, entity_code)
    standardised_frames.append(df)

# unionByName (allowMissingColumns=True) rather than union() because column order isn't
# guaranteed to match across the three source schemas even after the steps above.
treasury_positions_raw = standardised_frames[0]
for df in standardised_frames[1:]:
    treasury_positions_raw = treasury_positions_raw.unionByName(df, allowMissingColumns=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Write unified output to Delta

# COMMAND ----------

(
    treasury_positions_raw.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)

display(spark.table(OUTPUT_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks
# MAGIC
# MAGIC Quick counts to confirm the union picked up all rows from all three entities before
# MAGIC handing off to Notebook 2.

# COMMAND ----------

spark.table(OUTPUT_TABLE).groupBy("entity_code").count().show()
print(f"Total rows in {OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count()}")
