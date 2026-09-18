# Databricks notebook source
# MAGIC %md
# MAGIC # FX Utils: Live Rate Fetching
# MAGIC
# MAGIC Shared utility per `specs/fx-realtime-ingestion.md`. FX is a **live utility call**, not a
# MAGIC pre-populated data source — every USD conversion in Notebook 3/6 calls `get_live_rate()`
# MAGIC inline, at the moment the notebook runs, instead of reading a `fx_rates_clean` row that was
# MAGIC populated ahead of time. `%run` this notebook from Notebook 3/6 to import its functions.
# MAGIC
# MAGIC Uses `open.er-api.com` — the free, keyless "Open Access" tier of ExchangeRate-API. Chosen
# MAGIC over Open Exchange Rates specifically because it needs **no signup/API key**, matching this
# MAGIC project's preference for zero-manual-setup sources where one exists. **Its USD/EUR/LBP/SAR/
# MAGIC QAR coverage has not been verified against a live call in this session — confirm all 5
# MAGIC currencies are actually present in the response before relying on this for a demo.**

# COMMAND ----------

import time
import requests
from datetime import datetime, timezone
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

# COMMAND ----------

# MAGIC %md
# MAGIC ## `get_live_rate`
# MAGIC
# MAGIC Retries with backoff to absorb transient network blips (spec section 4), then raises —
# MAGIC callers must let that propagate and fail the calculation step loudly, per the spec's explicit
# MAGIC "don't silently fall back to a stale rate and present it as live" decision.

# COMMAND ----------

FX_API_BASE = "https://open.er-api.com/v6/latest"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def get_live_rate(currency_pair: str) -> tuple:
    """Fetches the live rate for a 'BASE/QUOTE' pair (e.g. 'USD/LBP') from the FX API.
    Returns (rate, fetched_at_iso_timestamp). Raises RuntimeError after MAX_RETRIES failed
    attempts — callers must not catch this and substitute a stale/hardcoded rate, since that
    would misrepresent a placeholder number as a live one (spec section 4)."""
    base, quote = currency_pair.upper().split("/")
    url = f"{FX_API_BASE}/{base}"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            payload = response.json()
            if payload.get("result") != "success":
                raise ValueError(f"API returned non-success result: {payload.get('result')}")
            rate = payload["rates"][quote]
            fetched_at = datetime.now(timezone.utc).isoformat()
            return float(rate), fetched_at
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise RuntimeError(
        f"get_live_rate failed for {currency_pair} after {MAX_RETRIES} attempts: {last_error}"
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Usage log
# MAGIC
# MAGIC Written *after* each live fetch, not read from beforehand — this is an audit byproduct
# MAGIC ("what rate did you actually use for this calculation"), not a lookup table (spec section 5).

# COMMAND ----------

FX_USAGE_LOG_TABLE = "fx_rate_usage_log"

_usage_log_schema = StructType([
    StructField("notebook_run_id", StringType(), False),
    StructField("currency_pair", StringType(), False),
    StructField("rate", DoubleType(), False),
    StructField("fetched_at", StringType(), False),
    StructField("used_in_calculation", StringType(), False),
    StructField("logged_at", TimestampType(), False),
])


def log_fx_usage(notebook_run_id: str, currency_pair: str, rate: float, fetched_at: str,
                  used_in_calculation: str) -> None:
    """Appends one row to fx_rate_usage_log. Append, not overwrite — every notebook run's fetches
    accumulate, since this is an audit trail, not a current-state table."""
    row = [(notebook_run_id, currency_pair, rate, fetched_at, used_in_calculation)]
    df = spark.createDataFrame(row, schema=[f.name for f in _usage_log_schema.fields[:-1]]) \
        .withColumn("logged_at", F.current_timestamp())
    (
        df.write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(FX_USAGE_LOG_TABLE)
    )


def get_live_rate_and_log(currency_pair: str, notebook_run_id: str, used_in_calculation: str) -> float:
    """Convenience wrapper: fetch + log in one call, returns just the rate — the shape every
    calculation site actually wants, so callers don't have to repeat the log_fx_usage boilerplate."""
    rate, fetched_at = get_live_rate(currency_pair)
    log_fx_usage(notebook_run_id, currency_pair, rate, fetched_at, used_in_calculation)
    return rate
