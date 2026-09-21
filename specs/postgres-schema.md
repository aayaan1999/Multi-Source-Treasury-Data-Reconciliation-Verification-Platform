# Spec: PostgreSQL Schema (Application Layer Foundation)

**Status:** DDL written at `db/schema.sql` (41 tables); syntax-checked with `pglast`, **not yet executed against a live
Postgres** (Docker Desktop wasn't running). SQLAlchemy models + Alembic migrations not yet written — see
section 4.
**Plan reference:** `PLATFORM-BUILD-PLAN.md` Phase 1, `3-WEEK-POC-PLAN.md` Track A Week 2
**Depends on:** nothing (foundational) — everything else in the application layer depends on this
**Source of truth:** `Middle East bank data cleaning and reporting.md`'s database section, plus
additions from this session's Camunda/sync/multi-source specs

---

## 1. Objective

Define the full PostgreSQL schema the FastAPI backend and Camunda bridge worker read/write
against — the "operational data store" Databricks output flows into.

## 2. Table Groups

### 2.1 Entity tables (mirror Databricks' `{table}_clean` shape, not `raw_*`)

`customers`, `accounts`, `loans`, `branches` — columns match
`specs/notebook-01-bank-data-ingestion.md`'s source schema exactly (this repo doesn't duplicate
the full column list here — see that spec). Primary keys: `customer_id`, `account_id`, `loan_id`,
`branch_id` respectively.

### 2.2 Time-series tables

`transactions`, `capital_positions`, `liquidity_daily`, `fx_rates` — same column shapes as the
Databricks source. **`fx_rates` specifically should mirror `fx_rates_live`** (append-only,
`fetched_at` timestamp) once `specs/fx-realtime-ingestion.md` is implemented, not the older
one-rate-per-day shape.

### 2.3 Gold-layer import tables (from Databricks nightly job)

`kpi_daily_summary`, `data_quality_exceptions`, `flagged_transactions`,
`exception_summary_by_table`, `exception_summary_by_flag`, plus Notebook 6's outputs
(`loan_breakdown_by_dimension`, `loan_stage_summary`, `top_exposures`, `loan_ageing_summary`,
`ltv_distribution`, `branch_performance_summary`, `segment_performance_summary`,
`product_performance_summary`, `scenario_snapshot`) — **column shapes are 1:1 with their
Databricks spec definitions** (`specs/notebook-03-kpi-summary.md`,
`specs/notebook-04-exception-summary.md`, `specs/notebook-06-portfolio-branch-scenario-snapshot.md`).
Don't re-derive these schemas independently — copy them from the notebook specs so the nightly
import job has no shape mismatch to reconcile.

### 2.4 Workflow/reporting tables (Screens 3 & 6)

`report_definitions`, `report_instances`, `report_line_items`, `validation_rules`,
`calculation_audit`, `risk_weights`, `submitted_files`, `users`, `roles`, `workflow_steps`,
`workflow_instances`, `tasks`, `comments`, `audit_log`, `limits`, `breaches` — per
`CLAUDE.md`'s existing enumeration, sourced from `Middle East bank data cleaning and reporting.md`.

**Note on `workflow_steps`/`workflow_instances`/`tasks`**: these were originally designed for a
status-column-based workflow (the source doc's original, non-Camunda recommendation). Since
Screen 6 now runs on Camunda 8 (`specs/camunda-bpmn-process-design.md`), Camunda's Zeebe engine
*is* the workflow state machine — these Postgres tables become a **read-side mirror** of Camunda
task state for querying/reporting purposes (e.g. Screen 6's own dashboards), not the source of
truth for in-flight workflow state. Don't build application logic that treats these tables as
authoritative for "is this task still open" — ask Zeebe/Tasklist for that.

### 2.5 New tables from this session's additions

- **`review_outcomes`** (`specs/bidirectional-sync.md`): `record_type`, `source_table`,
  `record_key`, `outcome`, `corrected_value` (JSON), `reviewed_by`, `reviewed_at`, `synced_at`
  (added per the watermark update in that spec)

**Deviations recorded while writing `db/schema.sql`:** (a) `fx_rates` keeps the `(date, currency_pair, rate)`
shape and a new `fx_rate_usage_log` table is added, because `specs/fx-realtime-ingestion.md` removed
`fx_rates_live`; (b) every Gold table carries `calculation_date` (notebooks 4 and 6 write it though
their spec column tables omit it); (c) `data_quality_exceptions` gains an app-side `exception_id`;
(d) the `report_*`, `risk_weights`, `validation_rules`, `calculation_audit` and `submitted_files`
columns are inferred — the source doc names only their purpose.
- **`transaction_code_mapping`** (`specs/multi-source-ingestion-adf.md` section 8): `source_system`,
  `source_code`, `centralized_code` — **schema defined, population blocked** on real source-system
  code lists; create the empty table now, don't wait to define its shape

## 3. Row-Level Security

Per `CLAUDE.md`'s stack decision, RLS enforces who-sees-what — e.g. a branch manager's session
should only see their own branch's rows in `branch_performance_summary`, not the whole bank's.
**Not yet designed in detail** — needs a concrete role model (which of the four seeded demo users —
analyst/reviewer/approver/admin — sees what) before RLS policies can be written. Flagging as an
open item, not implementing speculative policies.

## 4. Migrations

**SQLAlchemy + Alembic** (per `PLATFORM-BUILD-PLAN.md` Phase 1) — every table above becomes a
model + an Alembic migration. Build entity/time-series tables first (section 2.1-2.2), since
everything else depends on them existing before it can be seeded or imported into.

## 5. Acceptance Criteria

- [ ] Every table listed above exists with columns matching its source spec exactly (no
      independently-invented column names that drift from the Databricks output shape)
- [ ] Foreign keys enforced where the source doc's "how they join up" section implies them
      (`accounts.customer_id` → `customers.customer_id`, etc.)
- [ ] `review_outcomes` and `transaction_code_mapping` exist even though population is
      blocked/deferred — the shape shouldn't wait for the data
- [x] `db/schema.sql` written; parses as valid PostgreSQL and every FK target is created before its referrer
- [ ] Executed against a live Postgres (e.g. `docker run postgres:16` + `psql -f db/schema.sql`)
- [ ] Import check: load `bank-data/*.csv` (post-Notebook-2 shape) and confirm no column mismatch
- [ ] SQLAlchemy models + Alembic migrations generated from / reconciled with `db/schema.sql`

## 6. Non-Goals

- No RLS policy implementation (section 3 — blocked on role-model design)
- No data seeding (that's the synthetic data generator, a separate piece of work per
  `PLATFORM-BUILD-PLAN.md` Phase 1's "data reality check")
