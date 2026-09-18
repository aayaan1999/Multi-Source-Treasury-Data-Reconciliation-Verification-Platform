# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project State

**`Middle East bank data cleaning and reporting.md` is the source of truth for this entire
project** — the application layer (six screens, database schema) *and*, as of the Notebook 1-2
rewrite, the Databricks data layer too. `bank-x poc-brief.md` is retained as **historical
reference only**: it was the original, narrower brief (Bank x treasury reconciliation across
Lebanon/KSA/Qatar via Databricks + Appian) that kicked the project off, but every part of it —
Databricks scope (section 5) and Appian scope (section 6) alike — has since been superseded.
Don't build against `bank-x poc-brief.md` unless a spec file explicitly says otherwise.

Current build state: Notebooks 1-2 of the Databricks layer are built against the **bank-wide
schema** (`customers`, `accounts`, `loans`, `transactions`, `branches`, `capital_positions`,
`liquidity_daily`, `fx_rates` — see `Middle East bank data cleaning and reporting.md`), with
small hand-built sample CSVs in `bank-data/`. See `specs/notebook-01-bank-data-ingestion.md` and
`specs/notebook-02-bank-data-quality.md` for exact scope and acceptance criteria. The original
treasury-entity CSVs (`lebanon_positions.csv`, etc.) and the treasury-specific Notebooks 1-2 they
used to feed are **no longer used by any notebook** — kept in the repo as historical reference
(see `specs/day-01-sample-data-and-notebook-scaffolding.md`, marked superseded).

**Notebooks 3-4 are not yet rebuilt** and their original design (reading `treasury_positions_clean`
/ `treasury_positions_exceptions`) no longer applies, since Notebooks 1-2 no longer produce those
tables. Before building them, a new spec is needed defining what "Reconciliation & Consolidated
Report" and "Exception Summary" mean against the bank-wide schema's `{table}_clean` tables and
`data_quality_exceptions` log — don't assume the original brief's design still fits.

The entire application layer (PostgreSQL schema, FastAPI backend, React frontend) is not yet
built. See `PLATFORM-BUILD-PLAN.md` for the phased roadmap (note: its Phase 1 description of the
Databricks→Postgres import job references the old treasury table names and needs updating to
match the current `data_quality_exceptions`/`{table}_clean` output — flag this if picking up
that phase).

## What This Project Is

A platform that gives a Middle Eastern bank one system for: nightly data collection from its
core systems, automatic calculation of the ratios regulators and the board care about (capital
adequacy, liquidity, NPL, IFRS 9 staging, etc.), clean dashboards, "what-if" stress-test scenario
modelling, and a governed approval/audit-trail workflow for anything submitted to a regulator.

The differentiator over a plain BI tool: **Screen 6 (Report Workflow)** — prepare → review →
approve → submit, with a permanent, insert-only audit trail, and **Screen 3's drill-to-source**
— every number on a regulatory return is clickable back to the formula, source table, and record
count that produced it.

Databricks' `data_quality_exceptions` output (from Notebooks 1-2, against the bank-wide schema)
is this platform's first concrete data feed and first concrete workflow case — exactly the kind
of breach/exception record that Screen 6's task queue and approval chain are built to handle. The
original Bank x treasury-reconciliation use case that motivated this project is no longer the
data source; it's kept only as historical context for why this platform exists.

## Two-Layer Architecture

1. **Data layer — Databricks (PySpark, Delta Lake).** Ingests, standardises, and verifies source
   data nightly. This is the part Claude Code owns directly. It **was** treasury-specific but has
   been rewritten to match the source of truth's bank-wide schema — see "Databricks Build Scope"
   below.
2. **Application layer — FastAPI + PostgreSQL + React.** The six screens, the full banking data
   model, the workflow/audit-trail engine, scenario modelling, and PDF/Excel regulatory exports.
   Replaces the POC brief's Appian scope. See "Application Layer" below.

Handoff between the two layers: Databricks output tables (Delta + CSV export) are loaded into
PostgreSQL via a nightly import job — same file-based handoff philosophy as the original brief,
just landing in Postgres instead of Appian.

## Databricks Build Scope

Four PySpark notebooks against the bank-wide schema (`customers`, `accounts`, `loans`,
`transactions`, `branches`, `capital_positions`, `liquidity_daily`, `fx_rates`), all using Delta
Lake:

1. **Notebook 1 — Ingestion & Standardisation** (built) — reads the eight source CSVs
   (`bank-data/*.csv`), standardises date formats and numeric types, normalises `fx_rates`'
   currency-pair notation. Output: `raw_customers`, `raw_accounts`, `raw_loans`,
   `raw_transactions`, `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`,
   `raw_fx_rates`. Spec: `specs/notebook-01-bank-data-ingestion.md`.
2. **Notebook 2 — Data Quality Verification** (built) — runs structural + referential checks
   per table (27 flag labels total across the 8 tables — see the spec for the full list, e.g.
   `NPL_STAGE_MISMATCH`, `ORPHAN_CUSTOMER`, `DUPLICATE_RATE`). Output: `{table}_clean` per source
   table, plus one shared `data_quality_exceptions` log (`source_table`, `record_key`,
   `flag_label`, `description`) since the 8 source tables don't share a schema. Spec:
   `specs/notebook-02-bank-data-quality.md`.
3. **Notebook 3 — Reconciliation & Consolidated Report** (not yet built, **needs a new spec
   first** — its original design read treasury-specific tables that no longer exist).
4. **Notebook 4 — Exception Summary Report** (not yet built, same caveat as Notebook 3).

Conventions when building these notebooks: PySpark + `.format("delta")` for every output table;
inline comments explaining each transformation step (carried over from the original brief's
explicit requirement — an exception to the usual no-comments default, since these notebooks are
meant to be read by a Databricks developer unfamiliar with the code); write a spec file in
`specs/` before/alongside implementation (see existing specs for the format), including a
hand-traced acceptance/traceability table against the sample data, and mark unverified items
(e.g. "not run against a live cluster") rather than asserting they pass.

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

**Data reality check:** `bank-data/*.csv` (customers/accounts/loans/transactions/branches/
capital_positions/liquidity_daily/fx_rates) is small, hand-built sample data (6-10 rows/table)
created to exercise Notebook 2's checks — not a stand-in for realistic scale. The source doc
references "two million transactions" as a performance-proofing case; a proper synthetic data
generator at meaningful scale is still needed before Screens 1, 2, 4, 5 can be built and demoed
meaningfully (`PLATFORM-BUILD-PLAN.md` Phase 1). Flag this to the user before generating large
synthetic datasets rather than assuming scale/realism requirements.

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
