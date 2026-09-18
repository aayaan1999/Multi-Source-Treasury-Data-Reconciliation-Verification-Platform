# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project State

Two source documents shape this project, in this order of authority:

1. **`Middle East bank data cleaning and reporting.md`** — the current source of truth for the
   overall product: a bank-wide risk, regulatory-reporting, scenario-modelling, and workflow
   platform (six screens, full banking data model). Defer to this document for anything about
   the application layer, database schema, or screens.
2. **`bank-x poc-brief.md`** — the original, narrower POC brief (Bank x treasury reconciliation
   across Lebanon/KSA/Qatar via Databricks + Appian). Its Databricks scope (section 5) is still
   the spec for the data-ingestion layer and is unchanged. Its Appian scope (section 6) is
   **superseded** — the workflow/reporting application is now built as described in the source
   of truth doc instead of in Appian.

Current build state: sample entity CSVs exist (`lebanon_positions.csv`, `ksa_positions.csv`,
`qatar_positions.csv`), and Notebooks 1-2 of the Databricks layer are built
(`notebooks/01_ingestion_standardisation.py`, `notebooks/02_data_quality_verification.py`).
Notebooks 3-4 and the entire application layer (PostgreSQL schema, FastAPI backend, React
frontend) are not yet built. See `PLATFORM-BUILD-PLAN.md` for the phased roadmap.

## What This Project Is

A platform that gives a Middle Eastern bank one system for: nightly data collection from its
core systems, automatic calculation of the ratios regulators and the board care about (capital
adequacy, liquidity, NPL, IFRS 9 staging, etc.), clean dashboards, "what-if" stress-test scenario
modelling, and a governed approval/audit-trail workflow for anything submitted to a regulator.

The differentiator over a plain BI tool: **Screen 6 (Report Workflow)** — prepare → review →
approve → submit, with a permanent, insert-only audit trail, and **Screen 3's drill-to-source**
— every number on a regulatory return is clickable back to the formula, source table, and record
count that produced it.

The original Bank x treasury-reconciliation use case (three entities, FX/MM/liquidity positions,
data-quality exceptions) is this platform's first concrete data feed and first concrete workflow
case: Databricks' `treasury_positions_exceptions` output is exactly the kind of breach/exception
record that Screen 6's task queue and approval chain are built to handle.

## Two-Layer Architecture

1. **Data layer — Databricks (PySpark, Delta Lake).** Ingests, standardises, verifies, and
   reconciles source data nightly. This is the part Claude Code owns directly and it does not
   change with the new source of truth. See "Databricks Build Scope" below.
2. **Application layer — FastAPI + PostgreSQL + React.** The six screens, the full banking data
   model, the workflow/audit-trail engine, scenario modelling, and PDF/Excel regulatory exports.
   Replaces the POC brief's Appian scope. See "Application Layer" below.

Handoff between the two layers: Databricks output tables (Delta + CSV export) are loaded into
PostgreSQL via a nightly import job — same file-based handoff philosophy as the original brief,
just landing in Postgres instead of Appian.

## Databricks Build Scope (unchanged)

Per `bank-x poc-brief.md` section 5, four PySpark notebooks, run in sequence, all using Delta Lake:

1. **Notebook 1 — Ingestion & Standardisation** (built) — reads the three entity CSVs, standardises
   schema/dates/currency-pair notation, converts to USD. Output: `treasury_positions_raw`.
2. **Notebook 2 — Data Quality Verification** (built) — runs the 8 checks (`MISSING_DATE`,
   `MISSING_TRADER`, `INVALID_CCY_PAIR`, `INVALID_AMOUNT`, `RECONCILIATION_MISMATCH`,
   `LIMIT_BREACH`, `DUPLICATE_RECORD`, `CROSS_ENTITY_MISMATCH`). Output: `treasury_positions_clean`,
   `treasury_positions_exceptions`.
3. **Notebook 3 — Reconciliation & Consolidated Report** (not yet built) — group-level exposure
   by currency pair/entity/position type. Output: `treasury_consolidated_report`.
4. **Notebook 4 — Exception Summary Report** (not yet built) — exception counts by type/entity.
   Output: `exception_summary`.

Conventions when building these notebooks (still apply): PySpark + `.format("delta")` for every
output table; inline comments explaining each transformation step (explicit brief requirement,
an exception to the usual no-comments default); check whether sample CSVs exist before assuming
they do.

## Application Layer (FastAPI + PostgreSQL + React)

Per `Middle East bank data cleaning and reporting.md` — full detail lives there; this is the
orientation summary.

**Stack:** FastAPI (backend/API), PostgreSQL (database, row-level security for who-sees-what),
React + Tailwind + Recharts (frontend). Background jobs: APScheduler for a POC (Celery + Redis
only if scaling past POC). PDF export: ReportLab. Excel export: openpyxl. Auth: four seeded
demo users (analyst, reviewer, approver, admin) for the POC — Keycloak only if real SSO is
later required. **Do not reach for a workflow engine (e.g. Camunda) for the POC** — a status
column and a handful of endpoints cover the approval chain; this is explicit guidance in the
source doc, not a default to reconsider.

**Database — two kinds of tables:**
- *Entities:* `customers`, `accounts`, `loans`, `branches`
- *Time series:* `transactions`, `capital_positions` (monthly), `liquidity_daily`, `fx_rates`
- *Reporting/workflow (Screens 3 & 6):* `report_definitions`, `report_instances`,
  `report_line_items`, `validation_rules`, `calculation_audit`, `risk_weights`, `submitted_files`,
  `users`, `roles`, `workflow_steps`, `workflow_instances`, `tasks`, `comments`, `audit_log`,
  `limits`, `breaches`

Everything joins through ID columns (`customer_id`, `branch_id`, etc.) — see the source doc for
exact columns and the join logic behind each screen.

**Performance constraint (explicit, not optional):** screens must load in under ~2 seconds even
against millions of underlying transaction rows. Do **not** compute Screen 1/2/5's aggregates
live on page load — precompute nightly into small summary tables (e.g. `branch_performance_monthly`)
and have the screens read those. Scenario Modelling (Screen 4) must recompute in the browser
against an in-memory snapshot (~50 numbers) on every slider move, not query the database per
slider movement.

**The six screens** (detail in the source doc — build order is Claude Code's judgment call per
phase, see `PLATFORM-BUILD-PLAN.md`):
1. Executive Summary — 8 KPI tiles (CAR, LCR, NPL, NIM, cost-to-income, ROE, total assets,
   dollarization), 24-month trend, plain-language alert strip
2. Portfolio & Credit Risk — loan book sliced by product/segment/branch/currency, IFRS 9 staging,
   top-20 exposures, ageing table, LTV distribution
3. Regulatory Reporting — report calendar, regulator-format report view, drill-to-source on every
   number, validation checks, PDF/Excel export
4. Scenario Modelling — 4 sliders (devaluation, rate change, NPL increase, deposit outflow),
   waterfall chart, 12-month projection, base/adverse/severe presets
5. Branch & Segment Performance — branch league table, regional rollup, segment/product
   performance, efficiency quadrant scatter
6. Report Workflow — task queue, visual approval chain, review/comment/approve-or-return,
   auto-created breach tasks, insert-only audit trail

**Data reality check:** only the treasury positions data (via Databricks) is real/simulated per
an actual brief. Customers/accounts/loans/transactions/branches/capital/liquidity/FX data has no
source yet — will need a synthetic data generator before Screens 1, 2, 4, 5 can be built and
demoed meaningfully. Flag this to the user before generating large synthetic datasets rather than
assuming scale/realism requirements.

**Source file format assumption:** Notebook 1 currently reads CSV directly (`spark.read.csv`).
Spark also reads JSON/Parquet/Avro natively, and Excel with an added library — any of those are a
straightforward swap if a new source system exports differently. **PDF or scanned-image sources
are not a direct swap** — Spark can't parse those into rows/columns; they'd need a table-extraction
or OCR preprocessing step before anything reaches Notebook 1. Don't assume a newly-added source
system slots into the pipeline unchanged without confirming its actual export format first (see
`PREREQUISITES.md` open question 8).

## Roadmap

See `PLATFORM-BUILD-PLAN.md` for the phased build plan (Databricks layer, then Postgres/FastAPI
foundation, then screens in priority order, then workflow/audit-trail, then integration/demo
prep). `7-DAY-PLAN.md` is retained for its original scope (Databricks Days 1-3 only) — the app
layer no longer fits a 1-week timeline given the full platform scope.
