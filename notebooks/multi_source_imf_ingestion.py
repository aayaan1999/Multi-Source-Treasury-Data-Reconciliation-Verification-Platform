# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Ingestion: IMF Data API
# MAGIC
# MAGIC First of the 5 free-cloud-source ingestion notebooks from `specs/multi-source-ingestion-adf.md`
# MAGIC (section 9 has the full per-source implementation approach). Built first because it's the
# MAGIC only one of the five with zero manual setup — no account, no API key, just a public SDMX
# MAGIC endpoint. Stands in for a regulatory/macro data feed.
# MAGIC
# MAGIC This notebook calls the IMF's public SDMX 2.1 JSON API directly and lands the result in
# MAGIC Bronze. Per section 5 of the spec, Notebook 1 needs **zero awareness** of this notebook —
# MAGIC it only ever reads whatever file shape it's already configured for; this notebook's output
# MAGIC is a separate table, not one of the 8 `raw_*` bank tables.
# MAGIC
# MAGIC Input: none (public API call)
# MAGIC Output: Delta table `bronze_imf_macro`

# COMMAND ----------

import requests
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC
# MAGIC `IFS` (International Financial Statistics) is IMF's general-purpose macro dataset. The
# MAGIC series key below (`M.{country}.{indicator}`) follows SDMX's `frequency.ref_area.indicator`
# MAGIC convention — `M` for monthly. Countries picked to match this platform's MENA scope; the
# MAGIC indicator (`ENDA_XDC_USD_RATE`, period-average exchange rate to USD) is a plausible stand-in
# MAGIC for a regulator-relevant macro figure, not a specific requirement from the source doc.

# COMMAND ----------

dbutils.widgets.text("countries", "SA,QA,LB,AE", "Country codes (comma-separated, ISO2)")
dbutils.widgets.text("indicator", "ENDA_XDC_USD_RATE", "IFS indicator code")
dbutils.widgets.text("output_table", "bronze_imf_macro", "Output Delta table name")

COUNTRIES = dbutils.widgets.get("countries").split(",")
INDICATOR = dbutils.widgets.get("indicator")
OUTPUT_TABLE = dbutils.widgets.get("output_table")

IMF_BASE_URL = "http://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/IFS"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch
# MAGIC
# MAGIC One request per country rather than one combined request — if a single country's series is
# MAGIC missing or malformed, the rest still land. Failures are logged and skipped, not raised,
# MAGIC since a demo run against a live public API shouldn't fail entirely over one bad country
# MAGIC code; Notebook 2-equivalent quality checks are not in scope for this ingestion notebook.

# COMMAND ----------

def fetch_country_series(country: str, indicator: str) -> list:
    """Calls IMF's CompactData endpoint for one country/indicator series and returns a list of
    (country, indicator, period, value) tuples. Returns an empty list on any failure — this is a
    demo ingestion notebook, not a system of record, so a single bad series shouldn't block the
    other countries' data from landing."""
    series_key = f"M.{country}.{indicator}"
    url = f"{IMF_BASE_URL}/{series_key}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"WARNING: fetch failed for {series_key}: {exc}")
        return []

    try:
        series = payload["CompactData"]["DataSet"]["Series"]
    except (KeyError, TypeError):
        print(f"WARNING: unexpected response shape for {series_key}")
        return []

    # IMF returns a dict (single observation) or a list (multiple) under "Obs" — normalise to a list.
    observations = series.get("Obs", [])
    if isinstance(observations, dict):
        observations = [observations]

    rows = []
    for obs in observations:
        period = obs.get("@TIME_PERIOD")
        value = obs.get("@OBS_VALUE")
        if period is None or value is None:
            continue
        try:
            rows.append((country, indicator, period, float(value)))
        except ValueError:
            continue
    return rows

# COMMAND ----------

all_rows = []
for country in COUNTRIES:
    country = country.strip()
    if not country:
        continue
    fetched = fetch_country_series(country, INDICATOR)
    print(f"{country}: {len(fetched)} observations")
    all_rows.extend(fetched)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Bronze
# MAGIC
# MAGIC Explicit schema rather than `inferSchema` — this notebook builds the rows itself in Python,
# MAGIC so the shape is already known; an explicit schema also means an empty result (e.g. every
# MAGIC country's fetch failed) still produces a valid, queryable empty table instead of an error.

# COMMAND ----------

schema = StructType([
    StructField("country", StringType(), False),
    StructField("indicator", StringType(), False),
    StructField("period", StringType(), False),
    StructField("value", DoubleType(), True),
])

imf_df = spark.createDataFrame(all_rows, schema=schema).withColumn(
    "ingested_at", F.current_timestamp()
)

(
    imf_df.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

print(f"{OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count()} rows")
display(spark.table(OUTPUT_TABLE).orderBy("country", "period"))
