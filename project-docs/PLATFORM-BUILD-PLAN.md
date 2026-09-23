# Platform Build Plan

**Not the plan currently being executed.** `3-WEEK-POC-PLAN.md` is — it prioritizes a Camunda
8-based workflow extension over this plan's Phase 1-6 sequence. This document remains the
longer-term reference for the full 6-screen platform (Screens 2-5, scenario modelling, regulatory
reporting) once the 3-week scope is done, and its Phase 0/Phase 2 content (Databricks layer,
Screen 1 & 6 prioritization) is what `3-WEEK-POC-PLAN.md` builds on.

Phased roadmap for the full platform described in `Middle East bank data cleaning and reporting.md`.
Supersedes `7-DAY-PLAN.md` for everything past the Databricks layer — six screens on a real
banking data model is a multi-week build, not a 1-week POC. `7-DAY-PLAN.md` still stands for its
original Days 1-3 (Databricks sample data + notebooks).

Each phase below assumes ~1 week, adjust to actual team velocity. Phases are ordered so each one
produces something demoable, rather than front-loading all plumbing before anything is visible.

---

## Phase 0 — Databricks Data Layer (in progress)

Owner: Databricks Developer + Claude Code. Rebuilt against the bank-wide schema per
`Middle East bank data cleaning and reporting.md` — see `specs/notebook-01-bank-data-ingestion.md`
and `specs/notebook-02-bank-data-quality.md`. The original treasury-specific version of this
phase is historical (`specs/day-01-sample-data-and-notebook-scaffolding.md`, superseded).

**Next up, in order:** every notebook in this phase is now written — nothing is left to *write*
in Phase 0. What's left is entirely (1) a Databricks configuration/account-provisioning pass (see
the checklist this plan links to below) and (2) running everything against a real cluster and
checking output against each spec's traceability table. Do those in this order: (a) configure the
workspace basics (cluster, libraries, secret scope, Unity Catalog/schema) — needed before anything
runs at all; (b) run Notebooks 1 → 2 → IMF → 3/6 (parallel) → 4 → 5, checking each against its
spec's traceability table before moving to the next, since 3/4/5/6 all read Notebooks 1-2's
output; (c) provision the 4 remaining external accounts (Mockaroo, Neon, Salesforce, Google
Sheets) and run those ingestion notebooks — not blocking on the cluster-validation pass above,
can happen in parallel with it.

- [x] Sample CSVs for the 8 bank-wide tables (`bank-data/*.csv`) with injected data-quality issues
- [x] Notebook 1 — Ingestion & Standardisation → `raw_customers`, `raw_accounts`, `raw_loans`,
  `raw_transactions`, `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`, `raw_fx_rates`
- [x] Notebook 2 — Data Quality Verification → `{table}_clean` × 8, `data_quality_exceptions`
- [x] Notebook 3 — Nightly KPI Summary (`kpi_daily_summary`); written
  (`notebooks/03_kpi_summary.py`) per `specs/notebook-03-kpi-summary.md`. **Not yet run against a
  live cluster.** 3 of 8 KPIs (NIM, cost-to-income, ROE) use documented placeholder assumptions,
  not verified accounting.
- [x] Notebook 4 — Exception Summary (`exception_summary_by_table`, `exception_summary_by_flag`);
  written (`notebooks/04_exception_summary.py`) per `specs/notebook-04-exception-summary.md`.
  **Not yet run against a live cluster.**
- [x] Notebook 5 — Fraud & Business Rule Detection (`flagged_transactions`); written
  (`notebooks/05_fraud_business_rules.py`) per `specs/notebook-05-fraud-business-rules.md`. **Not
  yet run against a live cluster.**
- [x] Notebook 6 — Portfolio, Branch & Scenario Snapshot; written
  (`notebooks/06_portfolio_branch_scenario_snapshot.py`) per
  `specs/notebook-06-portfolio-branch-scenario-snapshot.md`. **Not yet run against a live
  cluster.**
- [x] Real-time FX rate utility (`get_live_rate()` + `fx_rate_usage_log`); written
  (`notebooks/fx_utils.py`) per `specs/fx-realtime-ingestion.md`, called from Notebooks 3/5/6.
  **Not yet run against a live cluster** — the chosen keyless API's LBP/SAR/QAR coverage is
  unverified. The old `fx_rates.csv` ingestion path in Notebook 1 was deliberately left in place
  rather than removed as a side effect of this work (see that spec's acceptance criteria).
- [x] Multi-source ingestion (`specs/multi-source-ingestion-adf.md`) — 5 free-cloud-source
  notebooks feeding Notebook 1's Bronze input, **all 5 now written**, none run yet:
  - [x] IMF Data API — `notebooks/multi_source_imf_ingestion.py`, no account needed, could run
    against a cluster today
  - [x] Mockaroo — `notebooks/multi_source_mockaroo_ingestion.py`, blocked on designing the mock
    schema + generating an API key
  - [x] Neon — `notebooks/multi_source_neon_ingestion.py`, blocked on provisioning a Neon project
  - [x] Salesforce — `notebooks/multi_source_salesforce_ingestion.py`, blocked on a Developer org
    signup + Connected App registration
  - [x] Google Sheets — `notebooks/multi_source_google_sheets_ingestion.py`, blocked on creating
    a service account + sharing a Sheet with it
- [ ] Run every notebook above against a real Databricks cluster and validate output against the
  traceability tables in the specs — **this is now Phase 0's single biggest remaining item**
- [ ] Scale up `bank-data/*.csv` (or generate separately) once realistic volume is needed —
  current sample data is notebook-testing size only (6-10 rows/table)

**Exit criteria:** all Delta tables produced and CSV-exportable; `data_quality_exceptions` is the
first real data feed into the application layer built from Phase 1 onward.

---

## Phase 1 — Foundation

Owner: Claude Code (backend/frontend scaffolding) + Dev Lead (environment decisions).

- [ ] PostgreSQL schema: all entity tables (`customers`, `accounts`, `loans`, `branches`),
  time-series tables (`transactions`, `capital_positions`, `liquidity_daily`, `fx_rates`), and
  workflow/reporting tables (`report_definitions`, `report_instances`, `report_line_items`,
  `validation_rules`, `calculation_audit`, `risk_weights`, `submitted_files`, `users`, `roles`,
  `workflow_steps`, `workflow_instances`, `tasks`, `comments`, `audit_log`, `limits`, `breaches`)
- [ ] FastAPI project skeleton with DB models + migrations (SQLAlchemy + Alembic)
- [ ] Synthetic data generator for customers/accounts/loans/transactions/branches/capital/liquidity/FX
  — no real source exists for these yet; check scale/realism expectations with the user before
  generating large volumes
- [ ] Nightly import job: Databricks CSV exports (`data_quality_exceptions`, plus the `{table}_clean`
  outputs once Phase 1's synthetic data generator gives them meaningful volume) → PostgreSQL tables
- [ ] React app skeleton: routing for all 6 screens (placeholder pages), Tailwind theming, seeded-user
  login (analyst/reviewer/approver/admin)
- [ ] `limits` table + a nightly breach-check job that creates `tasks`/`breaches` rows automatically

**Exit criteria:** empty-but-navigable app, seeded synthetic data in Postgres, Databricks output
flowing into Postgres nightly.

---

## Phase 2 — Screens 1 & 6 (the data-quality-exceptions demo case)

These two screens most directly cover the original project's motivating requirements (exception
review, approval, consolidated view, audit trail), so they come first — this is the fastest path
to a demoable story using data that's actually real (Databricks `data_quality_exceptions`
output), not synthetic.

- [ ] **Screen 6 — Report Workflow**: My Tasks landing view, visual approval chain (prepared →
  reviewed → approved → submitted), review screen with comments + approve/return-with-comment,
  breach alerts from Phase 1's `limits`/`breaches` tables, insert-only `audit_log` (enforce via DB
  grants: INSERT only, no UPDATE/DELETE)
  - Wire Databricks' `data_quality_exceptions` records in as the concrete task type here — this
    is what an officer actually reviews/approves/rejects, replacing the original brief's Appian
    Exception Queue + Case Detail concept
- [ ] **Screen 1 — Executive Summary**: 8 KPI tiles, 24-month trend chart, plain-language alert
  strip, nightly precomputed summary table (do not compute live)
  - CAR/LCR/NIM/ROE/cost-to-income/dollarization need `capital_positions`/`liquidity_daily`/
    `accounts`/`loans` data — real per Notebook 1-2's small sample, but at demo-meaningful scale
    only once Phase 1's synthetic data generator exists

**Exit criteria:** an officer can see an exception, claim/review it, approve or reject with a
mandatory comment, and see it reflected in an audit trail — the original brief's demo story,
running on the new stack.

---

## Phase 3 — Screen 3 (Regulatory Reporting)

- [ ] Report calendar (status: Not started → Draft → Under review → Approved → Submitted, coloured
  by urgency)
- [ ] Regulator-format report view (capital adequacy return as the first template)
- [ ] Drill-to-source: `calculation_audit` table populated alongside every calculated figure
  (formula text, source tables, filters, record count, timestamp) — this is the single feature
  the source doc calls out as mattering most to bankers/auditors
- [ ] Validation checks (`validation_rules` table) — block/warn/info severities
- [ ] PDF export (ReportLab) and Excel export (openpyxl) — test both thoroughly; a broken export
  button is explicitly called out as a deal-loser in the source doc

**Exit criteria:** a capital adequacy report can be opened, every line drilled to its source, and
exported to both PDF and Excel in the regulator's layout.

---

## Phase 4 — Screens 2 & 5 (Credit Risk, Branch/Segment Performance)

- [ ] **Screen 2 — Portfolio & Credit Risk**: loan book sliced by product/segment/branch/currency
  (each with total + bad-loan bars), 24-month NPL trend by product, IFRS 9 staging table + stage
  migration chart, top-20 exposures with %-of-capital, ageing table, LTV distribution
- [ ] **Screen 5 — Branch & Segment Performance**: branch league table, regional rollup, segment/
  product performance (net contribution = interest income − provisions), channel usage mix,
  efficiency quadrant scatter
  - Precompute `branch_performance_monthly` nightly — do not join branches→customers→accounts/loans
    live on page load

**Exit criteria:** both screens load in under ~2 seconds against the synthetic dataset and
correctly surface at least one clear "story" (e.g. one product driving NPL trend, one branch
losing money) for the demo narrative.

---

## Phase 5 — Screen 4 (Scenario Modelling)

Built last since it depends on stable figures from Screens 1-2 (capital, RWA, liquidity) to stress.

- [ ] In-memory snapshot on screen load (~50 numbers: loans by currency/product/rate-type, capital,
  liquidity, deposits by type) — sliders recompute against this snapshot in the browser, never
  querying the database per slider movement
- [ ] Four sliders (devaluation 0-50%, rate change ±5%, NPL increase 0-15%, deposit outflow 0-30%)
  with Base/Adverse/Severe presets
- [ ] Calculation order per the source doc: devaluation → revalue book → extra defaults it causes →
  independent NPL stress → new provisions → rate effects on profit → reduce capital → recompute
  RWA → recompute capital ratio → separately recompute liquidity
- [ ] Waterfall chart (today's ratio → each stressed factor → final ratio) and 12-month projection
  with the regulatory-minimum crossing point highlighted
- [ ] Assumptions stored in a settings table with a visible "Assumptions" link — not hardcoded

**Exit criteria:** moving a slider updates every downstream number with no visible delay, and the
waterfall chart correctly attributes impact across the four stress factors.

---

## Phase 6 — Integration, Polish, Demo Prep

- [ ] End-to-end rehearsal: Databricks notebooks run → exceptions flow into Postgres → officer
  resolves a case in Screen 6 → Screen 1/3 reflect the resolution → audit trail shows the full
  history
- [ ] Threshold/colour settings table tuned per-metric (red/amber/green cutoffs, since every
  regulator's floor differs)
- [ ] PDF/Excel export dry run under demo conditions
- [ ] Fix rough edges, freeze the demo environment

---

## Open Decisions to Revisit

- **Synthetic data scale**: source doc mentions "two million transactions" for performance-proofing
  the precomputed-summary approach — confirm with the user whether the demo needs that scale or a
  much smaller illustrative dataset is enough.
- **Hosting**: FastAPI + PostgreSQL + React need an actual deployment target (Azure App Service,
  AKS, or just local/dev for the demo) — not yet decided.
- **Auth**: seeded demo users are fine for a demo; note if the client will eventually need real SSO
  (Keycloak, per the source doc).
