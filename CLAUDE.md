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

**Notebooks 3-6, the live-FX utility (`notebooks/fx_utils.py`), and the five `multi_source_*`
ingestion notebooks are now written** (commit `a0bda22`) against their specs in `specs/`, but
**none of the Databricks notebooks has been verified on a live cluster yet** — verification is in
progress on Azure Databricks (catalog `dbw_bankx_treasury_poc`, schema `raw`, volume `raw`, CSVs in its `resources/` folder:
`/Volumes/dbw_bankx_treasury_poc/raw/raw/resources`; see `DATABRICKS-SETUP.md`). Treat every
acceptance-criteria checkbox as hand-traced, not proven, until a spec is updated to say otherwise.
Some spec `Status:` header lines (notebooks 3-6, `fx-realtime-ingestion.md`,
`multi-source-ingestion-adf.md`) still read "Spec only — not yet implemented" and are stale.

Notebooks follow a medallion layout: Bronze = `raw_*` (Notebook 1), Silver = `*_clean` and
`data_quality_exceptions` (Notebook 2), business-rule enrichment = `flagged_transactions`
(Notebook 5), Gold = the aggregates from Notebooks 3, 4 and 6. Every notebook's first code cell
pins `USE CATALOG dbw_bankx_treasury_poc` / `USE SCHEMA raw`, so tables are referenced by bare
name. Development flow: notebooks are edited and verified in Databricks (inside the Repo folder),
pushed to GitHub from there, then pulled locally — avoid editing `notebooks/` locally at the same
time.

**As of a 3-week timeline decision, the workflow architecture changed: Camunda 8 (self-hosted)
replaces the "status column + endpoints" design** the source doc originally recommended for a
plain POC — see "Workflow Engine Decision" below. `3-WEEK-POC-PLAN.md` is the current near-term
build plan; `PLATFORM-BUILD-PLAN.md` remains the longer-term full-6-screen-platform reference but
is **not the plan currently being executed** — don't build against its Phase 1-6 without checking
`3-WEEK-POC-PLAN.md` first for what's actually in scope right now.

Application layer: the PostgreSQL schema (`db/schema.sql`, on Neon) and a FastAPI skeleton
(`backend/`: login, health, read endpoints for Screens 1, 2, 4, 5 — see `specs/fastapi-backend.md`) are
built and tested locally, and `frontend/` (React + Vite + Tailwind + Recharts) has login and **Screen 1**
(Executive Summary — see `specs/screen-01-executive-summary.md`); the other five screens link to placeholders.
Screens 3 and 6 endpoints and Camunda are not built. Hosting plan: Netlify (frontend) + Render (backend) + Neon (database), configured in `netlify.toml` / `render.yaml`
and described in `DEPLOYMENT.md` (config verified locally; not yet deployed). Frontend commands: `cd frontend; npm run dev` / `npm test`
(always `npm run`, never `npx vite` — the folder name contains an `&`, which breaks Windows `.cmd` shims).

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

Handoff between the two layers: a Databricks Job (`databricks.yml`) runs notebooks 1-6 and then
`notebooks/load_to_postgres.py`, which merges the Silver/Gold Delta tables into PostgreSQL on
**Neon** in one transaction. The job starts by itself when a file lands in the landing volume
(file-arrival trigger), so results appear in the app minutes after an upload. Written and locally
tested, **not yet deployed** — see `specs/pipeline-job-and-neon-load.md`.

## Databricks Build Scope

Six PySpark notebooks (plus a future-phase seventh) against the bank-wide schema (`customers`, `accounts`, `loans`,
`transactions`, `branches`, `capital_positions`, `liquidity_daily`, `fx_rates`), all using Delta
Lake:

1. **Notebook 1 — Ingestion & Standardisation** (built, live-cluster verification in progress) — reads the eight source CSVs
   (`bank-data/*.csv`), standardises date formats and numeric types, normalises `fx_rates`'
   currency-pair notation. Output: `raw_customers`, `raw_accounts`, `raw_loans`,
   `raw_transactions`, `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`,
   `raw_fx_rates`. Spec: `specs/notebook-01-bank-data-ingestion.md`.
2. **Notebook 2 — Data Quality Verification** (built, not yet verified live) — runs structural + referential checks
   per table (27 flag labels total across the 8 tables — see the spec for the full list, e.g.
   `NPL_STAGE_MISMATCH`, `ORPHAN_CUSTOMER`, `DUPLICATE_RATE`). Output: `{table}_clean` per source
   table, plus one shared `data_quality_exceptions` log (`source_table`, `record_key`,
   `flag_label`, `description`) since the 8 source tables don't share a schema. Spec:
   `specs/notebook-02-bank-data-quality.md`.
3. **Notebook 3 — Nightly KPI Summary** (written, not yet verified on a live cluster) — precomputes 5 of
   the 8 Executive Summary KPIs (CAR, LCR, NPL ratio, total assets, dollarization ratio) from
   Notebook 2's clean tables; NIM/cost-to-income/ROE are explicitly blocked pending schema gaps
   (see the spec). Output: `kpi_daily_summary`. Spec: `specs/notebook-03-kpi-summary.md`.
4. **Notebook 4 — Exception Summary Report** (written, not yet verified on a live cluster) — summarises
   `data_quality_exceptions` by table and flag type, plus an exception-rate-per-table figure.
   Output: `exception_summary_by_table`, `exception_summary_by_flag`. Spec:
   `specs/notebook-04-exception-summary.md`.
5. **Notebook 5 — Fraud & Business Rule Detection** (written, not yet verified on a live cluster; new for
   the 3-week Camunda extension) — runs threshold-based fraud/business rules
   (`LARGE_AMOUNT`, `VELOCITY_BREACH`, `STRUCTURING_PATTERN`, `DUPLICATE_TRANSACTION`) against
   `transactions_clean`, separate from Notebook 2's structural checks since fraud and data-quality
   are different concerns. Output: `flagged_transactions` (mutable `status`, updated by human
   review — the one notebook output that isn't a clean overwrite-on-rerun). Spec:
   `specs/notebook-05-fraud-business-rules.md`.
6. **Notebook 6 — Portfolio, Branch & Scenario Snapshot** (written, not yet verified on a live cluster; new
   for the "no cuts, all 6 screens" plan revision) — Gold-layer aggregates feeding Screens 2, 4,
   and 5 (loan breakdown by dimension, IFRS 9 staging, top-20 exposures, ageing, LTV distribution,
   branch/segment/product performance, the Scenario Modelling snapshot). Reads only Notebook 2's
   clean tables (not Notebook 3), so Notebooks 3 and 6 can be built in parallel. Introduces its
   own documented assumptions (`PRODUCT_RATE_TYPE`, `ACCOUNT_RATE_TYPE`,
   `SEGMENT_COST_ALLOCATION`) alongside Notebook 3's. Spec:
   `specs/notebook-06-portfolio-branch-scenario-snapshot.md`.
7. **Notebook 7 — ML-Based Fraud/Anomaly Scoring** — **FUTURE PHASE, explicitly not in current
   scope.** Architecture documented (unsupervised Isolation Forest via MLflow batch scoring,
   combined with Notebook 5's deterministic rules per "AI gives a signal, not a decision") so the
   pipeline accommodates it later without rework — not because it's being built now. Real
   blockers (no labeled data, no behavioral baseline, no device telemetry) are documented in the
   spec itself. Spec: `specs/notebook-07-fraud-ml-future-phase.md`.

**Two more additions, both in current scope (unlike Notebook 7 above):**
- **Real-time FX rate fetching** — **not a polling job or a source table.** Currency-conversion
  logic inside Notebook 3/6 calls a shared `get_live_rate()` utility directly, inline, at the
  moment the notebook runs — the live rate is a utility call, not ingested data. This makes
  Notebook 1-2's old `fx_rates` ingestion path unnecessary (see the spec's section 2), and the
  `DUPLICATE_RATE`/`INVALID_RATE` checks in `specs/notebook-02-bank-data-quality.md` no longer
  apply once this is implemented (that spec's `fx_rates` row is marked superseded). Auditability
  is preserved via a `fx_rate_usage_log` written *after* each live fetch, not a pre-populated
  lookup table. Spec: `specs/fx-realtime-ingestion.md`.
- **Multi-source ingestion — revised to 5 free cloud sources, MVP scope.** Originally designed
  around Azure Data Factory + on-prem enterprise systems; revised once the actual scope was
  clarified as a demo/MVP using real free cloud services instead: **Neon** (Postgres, stands in
  for a core banking DB), **Mockaroo** (mock API, stands in for a loan origination system),
  **IMF's free public API** (regulatory/macro feed), **Salesforce Developer Edition** (real CRM,
  free), **Google Sheets** (branch/finance data). **ADF itself is no longer being stood up for
  this MVP** — small Databricks ingestion notebooks pull directly from these 5 sources instead;
  ADF remains documented as the enterprise-scale path if this ever needs real on-prem ERP/CRM
  integration. Still introduces the same real, currently-blocked schema gap
  (`transaction_code_mapping`, `source_system` column) needing actual source-system code lists —
  not resolvable with a placeholder assumption. Spec: `specs/multi-source-ingestion-adf.md`.

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
later required.

**Workflow Engine Decision (overrides the source doc's original guidance):** the source doc
originally said not to reach for a workflow engine like Camunda for a plain POC — a status column
and a handful of endpoints were meant to cover the approval chain. **For the 3-week Camunda
extension, that's overridden**: Screen 6's approval chain is now built on **Camunda 8,
self-hosted** (Zeebe + Elasticsearch + Operate + Tasklist via Docker Compose), not a Postgres
status column. React's Screen 6 calls Camunda Tasklist's REST API rather than a custom FastAPI
workflow endpoint. See `specs/camunda-bpmn-process-design.md` for the process design and
`3-WEEK-POC-PLAN.md` for why. If a future session is *not* working under that 3-week Camunda
scope, the original status-column guidance still applies — this override is specific to that
timeline decision, not a permanent architecture change to the source doc's own recommendation.

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

**`3-WEEK-POC-PLAN.md` is the plan currently being executed.** Per an explicit "no cuts" decision,
**all 6 screens are in scope for the 3-week demo**, not a subset — made possible only by (a) every
screen being "shallow-but-complete" rather than full source-doc depth (see that plan's
"Per-Screen Shallow Scope" section for exactly what's simplified per screen), and (b) the plan
assuming **~3 parallel workstreams** (data/Databricks, Camunda/workflow infra, React frontend),
not one person working sequentially — if actual team size is smaller, the timeline slips; that's
stated explicitly in the plan, not glossed over.

Three previously-blocked KPIs (NIM, Cost-to-Income, ROE — `specs/notebook-03-kpi-summary.md`) and
the Camunda Compliance-routing gap (`specs/camunda-bpmn-process-design.md`) are now resolved with
**documented placeholder assumptions**, not left blank, so all 8 KPI tiles and all 3 task-routing
groups actually work in the demo. These assumptions need a UI footnote wherever they feed a
number, and need confirming with whoever owns the source-of-truth doc — they make the demo
complete, not verified.

`PLATFORM-BUILD-PLAN.md` is the longer-term full-depth reference (what each screen looks like with
nothing shallow-cut) — still the eventual target once the 3-week window is done. `7-DAY-PLAN.md`
is retained for its original scope (Databricks Days 1-3 only, treasury-specific, now historical).
