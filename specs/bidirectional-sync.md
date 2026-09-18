# Spec: Bidirectional Sync — Postgres → Databricks

**Status:** Spec only — not yet implemented
**New for:** the 3-week Camunda-based POC extension — see `3-WEEK-POC-PLAN.md`
**Decision context:** overrides the original one-directional design ("An exception approved in
the application layer doesn't get looped back... file-based, one-directional integration only")
— the user's proposed end-to-end process explicitly requires Step 8, syncing reviewed/corrected
records back into Databricks so Gold-layer dashboards reflect review outcomes.

---

## 1. Objective

After a reviewer resolves a task in Camunda (Approved / Rejected / Corrected), get that outcome
back into the Databricks Gold layer so `kpi_daily_summary` and downstream dashboards reflect
reality — a rejected fraud transaction shouldn't keep counting toward exposure totals; a
corrected value shouldn't keep showing the wrong number.

## 2. Direction 1 (already covered elsewhere): Databricks → Postgres

Covered by `PLATFORM-BUILD-PLAN.md` Phase 1's nightly import job and
`specs/camunda-bpmn-process-design.md` section 4's bridge worker. Not repeated here.

## 3. Direction 2 (new): Postgres → Databricks

### What changes in Postgres

When a Camunda task completes, the service task (spec: `camunda-bpmn-process-design.md` section
3) writes to a Postgres table, e.g.:

```
review_outcomes(record_type, source_table, record_key, outcome, corrected_value, reviewed_by, reviewed_at)
```

`outcome` ∈ `{APPROVED, REJECTED, CORRECTED}`. `corrected_value` is nullable JSON (only populated
for `CORRECTED` outcomes) — the specific column(s) changed and their new values.

### How Databricks picks this up

**Recommended: scheduled JDBC read**, not a file re-export. Reading `review_outcomes` via Spark's
JDBC connector on each Notebook 3 run is simpler than exporting to ADLS and re-ingesting through
Auto Loader for what's a small, low-volume table (review decisions, not raw transaction volume).

```
review_outcomes_df = spark.read.jdbc(url=postgres_url, table="review_outcomes", properties=...)
```

### What Databricks does with it

A new step (either folded into Notebook 3 or a small standalone step run just before it):

1. For `REJECTED` fraud transactions: exclude that `transaction_id` from any Gold-layer
   aggregate that counts exposure/volume (e.g. it should no longer contribute to whatever
   transaction-volume metric Gold layer produces)
2. For `CORRECTED` data-quality records: apply `corrected_value` to the corresponding row in the
   relevant `{table}_clean` table (e.g. a corrected `risk_rating` on a `customers_clean` row)
   before Notebook 3 aggregates it
3. For `APPROVED`: no data change — the record was reviewed and confirmed fine, already counted

### Idempotency — now built as a watermark, per the multi-source ingestion decision

Originally deferred ("reprocess the whole table each run, simpler for POC scale"). Now formalized,
consistent with the same watermark approach `specs/multi-source-ingestion-adf.md` section 5 uses
for source-database ingestion — keeping both directions of this pipeline on the same incremental
pattern rather than one being watermarked and the other a full-table reload:

- `review_outcomes` gets a `synced_at` column, set by Databricks after processing a row (not by
  Postgres/Camunda when the row is written — this distinguishes "when the decision was made" from
  "when Databricks last picked it up")
- Each run: `WHERE reviewed_at > :last_watermark` (the max `reviewed_at` Databricks has already
  processed, tracked in a small checkpoint table or file), not a full-table read
- **This is a simple watermark-column approach, not log-based CDC (Debezium).** Research into
  Postgres CDC options for this session confirmed Debezium (WAL-based, via a replication slot and
  typically a Kafka broker) is the production-grade pattern — but it requires real operational
  setup (`wal_level = logical`, replication-slot lag monitoring, WAL-retention limits) that isn't
  warranted for a low-volume table like `review_outcomes`. A watermark column is the right-sized
  choice at this scale; Debezium remains the documented upgrade path if this table's write volume
  or freshness requirements ever justify it.

## 4. Latency

This sync runs on the same nightly cadence as the rest of the pipeline (Notebook 3's run),
**not real-time**. A reviewer's decision won't be reflected on the Executive Summary screen until
the next nightly run. This is consistent with the rest of the pipeline's batch philosophy and
should be stated explicitly in the demo narrative — "reviewed this morning, reflected in
tomorrow's report" is a very different claim than "reflected instantly," and overstating it during
a demo would be a credibility risk with a banking audience that will ask.

## 5. Acceptance Criteria

- [ ] `review_outcomes` table exists in Postgres and is written to by the Camunda service task
- [ ] A JDBC read of `review_outcomes` succeeds from a Databricks notebook
- [ ] A `REJECTED` fraud transaction is excluded from the next Gold-layer aggregate run
- [ ] A `CORRECTED` data-quality record's corrected value is reflected in the next `{table}_clean`
      read, without needing a full Notebook 1-2 rerun
- [ ] Not yet implemented

## 6. Non-Goals

- No real-time/event-driven sync (explicitly batch, matching the rest of the pipeline)
- No conflict resolution for a record reviewed twice or corrected inconsistently — out of scope
  for a POC; would need real design (last-write-wins? reviewer role precedence?) before production
- No Debezium/log-based CDC (see the "Idempotency" section — a watermark column is the right-sized
  choice at this table's scale)

---

**Research sources** (grounding the watermark-vs-CDC decision, fetched during this session):
- [PostgreSQL CDC: Logical Replication vs Debezium vs Native Streaming | RisingWave](https://risingwave.com/blog/postgresql-cdc-logical-replication-debezium/)
- [Debezium in Production: PostgreSQL to Kafka to Iceberg CDC Patterns That Actually Work](https://bigdataboutique.com/blog/debezium-production-cdc-patterns)
