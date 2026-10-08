# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Source Reconciliation (core banking and CRM)
# MAGIC
# MAGIC **Two sources, chosen with the `source` parameter** (default `neon`):
# MAGIC * `neon` - core banking, as below. Connected from the app's Data ingestion tab as PostgreSQL and
# MAGIC   run as the `core_banking_reconciliation` task (added 2026-10-08), which skips when that run didn't
# MAGIC   load core banking, like the CRM task.
# MAGIC * `los` - the loan origination system (added 2026-10-08), connected as REST API: each loan in
# MAGIC   `bronze_los_loans` (`multi_source_rest_api_ingestion.py`) is matched to ours by `loan_id` and
# MAGIC   compared on customer, product, currency, principal, outstanding and interest rate. Runs as the
# MAGIC   `loans_api_reconciliation` task and skips when that run didn't load the loan system.
# MAGIC * `salesforce` - the CRM (added 2026-09-29): each Salesforce Account (`bronze_salesforce_accounts`,
# MAGIC   from `multi_source_salesforce_ingestion.py`) is matched to our customer by Account Number =
# MAGIC   `customer_id` and compared on `name` and `country`, against our Corporate and SME customers only
# MAGIC   (a CRM holds business customers, so retail customers missing from it aren't breaks). Runs as the
# MAGIC   `salesforce_reconciliation` task, and skips when that run didn't load Salesforce, so stale CRM
# MAGIC   data is never compared. Everything below the comparison - automatic clearing, ageing, keeping
# MAGIC   reviewers' decisions - is shared, keyed by `source_system`.
# MAGIC
# MAGIC Per `specs/multi-source-reconciliation.md`. Compares `bronze_neon_customers` /
# MAGIC `bronze_neon_accounts` (written by `multi_source_neon_ingestion.py`, standing in for the
# MAGIC Core Banking System) against this platform's own canonical `customers_clean` /
# MAGIC `accounts_clean` (Notebook 2's Silver output), and flags any field where the two disagree.
# MAGIC
# MAGIC **This is a different question from Notebook 2's checks.** Notebook 2 asks "is this row
# MAGIC internally valid" (nulls, bad enums, broken foreign keys). This notebook asks "do two
# MAGIC independent systems agree about the same customer/account" — the actual "reconciliation" in
# MAGIC this project's name, which the bank-wide schema rewrite dropped and this notebook restores,
# MAGIC scoped to the one multi-source pair that's a genuine same-entity comparison (see the spec
# MAGIC section 3 for why Mockaroo/Salesforce/IMF/Google Sheets aren't included yet).
# MAGIC
# MAGIC **Requires the same external setup `multi_source_neon_ingestion.py` needs** (a separate demo
# MAGIC Neon project standing in for core banking, with `bronze_neon_customers`/`bronze_neon_accounts`
# MAGIC populated by that notebook) **and needs that source's data deliberately seeded with a mix of
# MAGIC matches, mismatches and missing records** (spec section 4) — without that, this notebook runs
# MAGIC cleanly but finds nothing, which proves nothing. Written but unrun until both are done.
# MAGIC
# MAGIC Input: `bronze_neon_customers`, `bronze_neon_accounts`, `bronze_salesforce_accounts`, `bronze_los_loans`,
# MAGIC `customers_clean`, `accounts_clean`, `loans_clean`
# MAGIC Output: Delta table `reconciliation_exceptions`

# COMMAND ----------

# Pin every table read/write to one catalog + schema so bare table names resolve the same way in
# every notebook (the workspace's existing catalog `dbw_bankx_treasury_poc`; Default Storage blocks CREATE CATALOG via SQL).
spark.sql("USE CATALOG dbw_bankx_treasury_poc")
spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
spark.sql("USE SCHEMA raw")

# COMMAND ----------

from delta.tables import DeltaTable
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# COMMAND ----------

# MAGIC %md
# MAGIC ## Numeric tolerance
# MAGIC
# MAGIC Differences under this amount don't flag - rounding noise, not a real disagreement. See spec
# MAGIC section 5; the $1.00 figure is illustrative, same caveat as every other POC threshold in this
# MAGIC repo (Notebook 5's $50,000 large-amount rule, Notebook 6's placeholder assumptions).

# COMMAND ----------

NUMERIC_TOLERANCE_USD = 1.00
RATE_TOLERANCE = 0.001          # interest rates are percentages (6.5 = 6.5%): only a real rate difference flags

# COMMAND ----------

dbutils.widgets.text("source", "neon", "Which source to reconcile: neon (core banking), salesforce (CRM) or los (loan system)")
SOURCE = dbutils.widgets.get("source").strip().lower()
if SOURCE not in ("neon", "salesforce", "los"):
    raise ValueError(f"Unknown source {SOURCE!r}: use neon, salesforce or los")

if SOURCE == "salesforce":
    # Only compare CRM data loaded in this same run; debugValue lets the notebook run by hand too.
    loaded = dbutils.jobs.taskValues.get(taskKey="salesforce_ingest", key="status", default="skipped", debugValue="loaded")
    if loaded != "loaded" or not spark.catalog.tableExists("bronze_salesforce_accounts"):
        dbutils.notebook.exit(f"skipped: Salesforce was not loaded in this run ({loaded})")
else:
    # Same for core banking (connected as PostgreSQL in the app) and the loan system (REST API): never
    # compare a snapshot an earlier run left behind.
    ingest_task, what = {"neon": ("core_banking_ingest", "core banking"), "los": ("loans_api_ingest", "the loan system")}[SOURCE]
    loaded = dbutils.jobs.taskValues.get(taskKey=ingest_task, key="status", default="skipped", debugValue="loaded")
    if loaded != "loaded":
        dbutils.notebook.exit(f"skipped: {what} was not loaded in this run ({loaded})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Latest row per entity
# MAGIC
# MAGIC `multi_source_neon_ingestion.py` appends incrementally (a watermarked pull, not a full
# MAGIC snapshot each run), so a customer/account that's changed since the first pull has more than
# MAGIC one row in `bronze_neon_*`. Reconciliation compares against the *current* state, so this
# MAGIC takes only the most-recently-ingested row per entity.

# COMMAND ----------

def latest_per_entity(table_name: str, entity_col: str):
    if not spark.catalog.tableExists(table_name):
        return None
    window = Window.partitionBy(entity_col).orderBy(F.col("ingested_at").desc())
    return (
        spark.table(table_name)
        .withColumn("_rn", F.row_number().over(window))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )

if SOURCE == "neon":
    bronze_customers = latest_per_entity("bronze_neon_customers", "customer_id")
    bronze_accounts = latest_per_entity("bronze_neon_accounts", "account_id")

# COMMAND ----------

# MAGIC %md
# MAGIC ## One row per entity on the canonical side too
# MAGIC
# MAGIC `customers_clean`/`accounts_clean` are overwritten fresh each Notebook 2 run
# MAGIC (`specs/notebook-02-bank-data-quality.md`), so there's no legitimate reason for more than one
# MAGIC row per `customer_id`/`account_id` - but Delta tables carry no primary-key constraint, so a
# MAGIC duplicate slipping in upstream (a re-ingested raw file, a bad join elsewhere) isn't caught
# MAGIC anywhere before it gets here. Confirmed live (2026-09-23): without this, `reconcile()`'s full
# MAGIC outer join fanned out N-for-N on every duplicated entity - 469 entities each produced 4
# MAGIC identical exception rows, all with the same detected_at, because accounts_clean/customers_clean
# MAGIC held 4 duplicate rows per key. dropDuplicates(key) takes one arbitrary row per key rather than
# MAGIC picking "latest" (there's no ingested_at-equivalent column here to order by, and since a
# MAGIC correctly-functioning pipeline never legitimately has two different rows for the same key,
# MAGIC arbitrary-but-single is the right defensive behaviour, not a data-loss risk).

# COMMAND ----------

def dedupe_canonical(df, key_col: str):
    return df.dropDuplicates([key_col])

canonical_customers = dedupe_canonical(spark.table("customers_clean"), "customer_id")
canonical_accounts = dedupe_canonical(spark.table("accounts_clean"), "account_id")
canonical_loans = dedupe_canonical(spark.table("loans_clean"), "loan_id")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compare one entity type
# MAGIC
# MAGIC Full outer join on the shared key, then one output row per compared field that differs
# MAGIC beyond tolerance, plus one row per entity that exists on only one side. `fields` is
# MAGIC `[(column, tolerance), ...]` — a numeric column gives its tolerance (a difference larger than it
# MAGIC flags), a text column gives None and needs an exact match.

# COMMAND ----------

def reconcile(bronze_df, canonical_df, entity_type: str, key_col: str, fields: list):
    if bronze_df is None:
        print(f"{entity_type}: no {SOURCE} data to compare - skipping (source not ingested yet)")
        return None

    joined = bronze_df.alias("src").join(
        canonical_df.alias("can"), F.col(f"src.{key_col}") == F.col(f"can.{key_col}"), "full_outer"
    )

    missing_in_canonical = (
        joined.filter(F.col(f"can.{key_col}").isNull())
        .select(
            F.lit(entity_type).alias("entity_type"),
            F.col(f"src.{key_col}").alias("entity_id"),
            F.lit(None).cast("string").alias("field_name"),
            F.lit(None).cast("string").alias("source_value"),
            F.lit(None).cast("string").alias("canonical_value"),
            F.lit("MISSING_IN_CANONICAL").alias("mismatch_type"),
        )
    )
    missing_in_source = (
        joined.filter(F.col(f"src.{key_col}").isNull())
        .select(
            F.lit(entity_type).alias("entity_type"),
            F.col(f"can.{key_col}").alias("entity_id"),
            F.lit(None).cast("string").alias("field_name"),
            F.lit(None).cast("string").alias("source_value"),
            F.lit(None).cast("string").alias("canonical_value"),
            F.lit("MISSING_IN_SOURCE").alias("mismatch_type"),
        )
    )

    matched = joined.filter(F.col(f"src.{key_col}").isNotNull() & F.col(f"can.{key_col}").isNotNull())
    value_mismatches = None
    for field, tolerance in fields:
        src_col, can_col = F.col(f"src.{field}"), F.col(f"can.{field}")
        differs = (
            (F.abs(src_col.cast("double") - can_col.cast("double")) > tolerance)
            if tolerance is not None
            else (src_col != can_col)
        )
        field_mismatches = (
            matched.filter(differs)
            .select(
                F.lit(entity_type).alias("entity_type"),
                F.col(f"src.{key_col}").alias("entity_id"),
                F.lit(field).alias("field_name"),
                src_col.cast("string").alias("source_value"),
                can_col.cast("string").alias("canonical_value"),
                F.lit("VALUE_MISMATCH").alias("mismatch_type"),
            )
        )
        value_mismatches = field_mismatches if value_mismatches is None else value_mismatches.unionByName(field_mismatches)

    parts = [p for p in [missing_in_canonical, missing_in_source, value_mismatches] if p is not None]
    result = parts[0]
    for p in parts[1:]:
        result = result.unionByName(p)
    return result

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run both comparisons
# MAGIC
# MAGIC Compared fields per spec section 5: customers on `name`/`segment`/`risk_rating`/`branch_id`
# MAGIC (all text - exact match), accounts on `type`/`currency` (text) and `balance` (numeric,
# MAGIC tolerance-checked).

# COMMAND ----------

if SOURCE == "neon":
    customer_fields = [("name", None), ("segment", None), ("risk_rating", None), ("branch_id", None)]
    account_fields = [("type", None), ("currency", None), ("balance", NUMERIC_TOLERANCE_USD)]

    customer_exceptions = reconcile(bronze_customers, canonical_customers, "customer", "customer_id", customer_fields)
    account_exceptions = reconcile(bronze_accounts, canonical_accounts, "account", "account_id", account_fields)

    parts = [e for e in [customer_exceptions, account_exceptions] if e is not None]
elif SOURCE == "los":
    # Loan system side: one row per loan_id (the Bronze table is a fresh snapshot, but an API can repeat a record).
    los_loans = spark.table("bronze_los_loans").dropDuplicates(["loan_id"])
    loan_fields = [("customer_id", None), ("product", None), ("currency", None),
                   ("principal", NUMERIC_TOLERANCE_USD), ("outstanding", NUMERIC_TOLERANCE_USD), ("interest_rate", RATE_TOLERANCE)]
    parts = [reconcile(los_loans, canonical_loans, "loan", "loan_id", loan_fields)]
else:
    # CRM side: one row per Account. An Account without an Account Number can't be matched to anyone,
    # so it keeps its Salesforce Id ("SF:001...") and shows as missing in our data.
    crm_customers = (
        spark.table("bronze_salesforce_accounts")
        .select(
            F.coalesce(F.trim(F.col("AccountNumber")), F.concat(F.lit("SF:"), F.col("Id"))).alias("customer_id"),
            F.trim(F.col("Name")).alias("name"),
            F.trim(F.col("BillingCountry")).alias("country"),
        )
        .dropDuplicates(["customer_id"])
    )
    business_customers = canonical_customers.filter(F.col("segment").isin("Corporate", "SME")).select("customer_id", "name", "country")
    parts = [reconcile(crm_customers, business_customers, "customer", "customer_id", [("name", None), ("country", None)])]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Merge into `reconciliation_exceptions`
# MAGIC
# MAGIC `status` is set to `OPEN` only for genuinely new
# MAGIC `(source_system, entity_type, entity_id, field_name, mismatch_type)` combinations - a rerun
# MAGIC must not reset a row a reviewer has already actioned, same discipline as
# MAGIC `flagged_transactions` (`specs/notebook-05-fraud-business-rules.md`).
# MAGIC
# MAGIC Added for client point 1 (`specs/reconciliation-groups.md`):
# MAGIC * **Automatic clearing:** a text difference that disappears once case, spaces and punctuation are
# MAGIC   ignored ("AL-HASSAN TRADING" vs "Al Hassan Trading") is recorded as `AUTO_ACCEPTED` with the
# MAGIC   rule that cleared it, never sent to a person. (Numeric differences within the tolerance above
# MAGIC   aren't recorded at all.)
# MAGIC * **Ageing / recurring:** a break found again updates `last_seen` and `times_seen`; the Postgres
# MAGIC   load reopens one a reviewer had resolved (`recurring`) rather than letting it pass silently.

# COMMAND ----------

if not parts:
    print("No source data to reconcile against yet (bronze_neon_customers/bronze_neon_accounts missing).")
else:
    all_exceptions = parts[0]
    for p in parts[1:]:
        all_exceptions = all_exceptions.unionByName(p)

    # Formatting-only: the same text once upper-cased and stripped of spaces and punctuation.
    def letters_and_digits(col):
        return F.regexp_replace(F.upper(F.col(col)), "[^A-Z0-9]", "")

    formatting_only = (
        (F.col("mismatch_type") == "VALUE_MISMATCH")
        & F.col("source_value").isNotNull() & F.col("canonical_value").isNotNull()
        & (letters_and_digits("source_value") == letters_and_digits("canonical_value"))
    )
    now = F.current_timestamp()
    all_exceptions = (
        all_exceptions.withColumn("source_system", F.lit(SOURCE))
        .withColumn("status", F.when(formatting_only, F.lit("AUTO_ACCEPTED")).otherwise(F.lit("OPEN")))
        .withColumn("resolved_rule", F.when(formatting_only, F.lit("FORMATTING_ONLY")))
        .withColumn("detected_at", now)
        .withColumn("first_seen", now)
        .withColumn("last_seen", now)
        .withColumn("times_seen", F.lit(1))
        .withColumn("resolved_by", F.lit(None).cast("string"))
        .withColumn("resolved_at", F.when(formatting_only, now).otherwise(F.lit(None).cast("timestamp")))
        .withColumn("resolution_note", F.when(formatting_only, F.lit("Cleared automatically: formatting only")))
        .select("source_system", "entity_type", "entity_id", "field_name", "source_value",
                "canonical_value", "mismatch_type", "status", "detected_at",
                "resolved_by", "resolved_at", "resolution_note", "resolved_rule",
                "first_seen", "last_seen", "times_seen")
    )

    merge_key = (
        "t.source_system = s.source_system AND t.entity_type = s.entity_type "
        "AND t.entity_id = s.entity_id AND t.mismatch_type = s.mismatch_type "
        "AND (t.field_name = s.field_name OR (t.field_name IS NULL AND s.field_name IS NULL))"
    )

    if spark.catalog.tableExists("reconciliation_exceptions"):
        # Tables created before these columns existed get them added (older rows: first/last seen =
        # when they were detected, seen once).
        existing = set(spark.table("reconciliation_exceptions").columns)
        for col, sql_type in [("resolved_rule", "STRING"), ("first_seen", "TIMESTAMP"), ("last_seen", "TIMESTAMP"), ("times_seen", "INT")]:
            if col not in existing:
                spark.sql(f"ALTER TABLE reconciliation_exceptions ADD COLUMNS ({col} {sql_type})")
        if "first_seen" not in existing:
            spark.sql("UPDATE reconciliation_exceptions SET first_seen = detected_at, last_seen = detected_at, times_seen = 1")
        target = DeltaTable.forName(spark, "reconciliation_exceptions")
        (
            target.alias("t").merge(all_exceptions.alias("s"), merge_key)
            # Seen again: when, and how many runs it has appeared in. Status stays the app's.
            .whenMatchedUpdate(set={"last_seen": "s.last_seen", "times_seen": "t.times_seen + 1"})
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        all_exceptions.write.format("delta").mode("overwrite").saveAsTable("reconciliation_exceptions")

    print(f"reconciliation_exceptions total rows: {spark.table('reconciliation_exceptions').count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity checks

# COMMAND ----------

if spark.catalog.tableExists("reconciliation_exceptions"):
    display(
        spark.table("reconciliation_exceptions")
        .groupBy("entity_type", "mismatch_type", "status")
        .count()
        .orderBy("entity_type", "mismatch_type")
    )
