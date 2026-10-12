# Platform Overview: Important Files and What They Do

A high-level map of the platform for whoever owns it. Written 2026-10-12 from `CLAUDE.md`, the
folder layout and the opening descriptions of the main files. It is a starting point, not a
complete reference. For depth, go to the source-of-truth doc and the per-feature specs in `specs/`.

---

## What the platform is

A reporting and governance platform for a Middle Eastern bank. It has three main parts:

1. **Databricks (data layer):** each night it pulls in the bank's data, cleans and checks it, and
   calculates the ratios regulators and the board watch.
2. **The web app (FastAPI + Postgres on Neon + React):** dashboards, regulatory reports, what-if
   scenarios, a reconciliation screen, and a plain-English question box ("Ask").
3. **Camunda 8 (self-hosted in Docker):** runs the human review and approval steps, such as fraud
   flags, limit breaches and reconciliation differences.

```
Source CSVs / core banking (Neon) / loan API (Supabase) / Salesforce
        │
        ▼
Databricks job (databricks.yml) ── Bronze raw_* → Silver *_clean → Gold aggregates
        │  load_to_postgres.py (all tables merged in one transaction)
        ▼
Postgres on Neon ◄──── FastAPI backend (backend/app) ◄──── React frontend (frontend/src)
        ▲                                                    │
        │  bridge workers (camunda/bridge)                    │ calls Tasklist REST directly
        └────────────── Camunda 8 (Zeebe + Tasklist) ◄───────┘
```

---

## 1. Data layer: `notebooks/` + `databricks.yml`

**`databricks.yml`** defines the Databricks job `bank-data-pipeline`. It runs by itself when a
file arrives in the landing volume (after a 10-minute quiet period), or when someone clicks
**Run now**. It has 14 steps:

```
ingest → quality → ┬ kpi_summary
                   ├ exception_summary
                   ├ fraud_rules
                   ├ portfolio_snapshot
                   ├ pipeline_reconciliation
                   ├ salesforce_ingest   → salesforce_reconciliation
                   ├ core_banking_ingest → core_banking_reconciliation
                   └ loans_api_ingest    → loans_api_reconciliation
                                         → load_postgres (after all of the above)
```

| File | Purpose |
|---|---|
| `01_ingestion_standardisation.py` | Reads the 8 source CSVs, standardises dates and numbers, writes the `raw_*` tables (Bronze) |
| `02_data_quality_verification.py` | 27 data-quality checks; writes `*_clean` tables plus a shared `data_quality_exceptions` log (Silver) |
| `03_kpi_summary.py` | Calculates the 8 headline ratios (CAR, LCR, NPL, NIM, cost-to-income, ROE, total assets, dollarisation) into `kpi_daily_summary` |
| `04_exception_summary.py` | Exception counts and rates per table and per check |
| `05_fraud_business_rules.py` | Fraud rules (large amount, too many transactions too fast, split payments that stay under limits, duplicates); writes `flagged_transactions` |
| `06_portfolio_branch_scenario_snapshot.py` | Summary tables for the Portfolio, Branch and Scenario screens |
| `fx_utils.py` | `get_live_rate()`: fetches the live exchange rate inline and logs each use to `fx_rate_usage_log` |
| `pipeline_reconciliation.py` | Compares what each source *sent* with what *survived cleaning*, so no rows are lost silently |
| `multi_source_*_ingestion.py` | Pull data from outside systems: Neon (core banking), REST API (loan origination), Salesforce (CRM), plus IMF, Mockaroo and Google Sheets |
| `multi_source_reconciliation.py` | Compares our clean data against core banking, the loan system or the CRM (chosen by its `source` parameter); writes `reconciliation_exceptions` |
| **`load_to_postgres.py`** | **Copies everything from Databricks into Postgres.** Writes to a staging schema first, then merges into the live tables in one transaction, so dashboards never see half-loaded data |

---

## 2. Database: `db/`

- **`schema.sql`**: the base schema. It has the 8 core bank tables (`customers`, `accounts`,
  `loans`, `transactions`, `branches`, `capital_positions`, `liquidity_daily`, `fx_rates`), plus
  reporting and workflow tables such as `report_*`, `users`, `audit_log`, `limits` and `breaches`.
- **`migrations/001…023_*.sql`**: every change made since, in order. Apply them with
  `python db/apply_migration.py <file>`. If the backend returns a 503 saying a table or column is
  missing, a migration hasn't been applied.

---

## 3. Backend: `backend/app/`

| File | Purpose |
|---|---|
| **`main.py`** | Starts the app. Mounts the routers under `/api/v1` and adds per-screen access checks and a read-only guard |
| **`roles.py`** | One table defining the 7 demo roles (CFO, CRO, Reconciliation Analyst, Reporting Officer, Compliance Officer, Internal Auditor, Platform Admin): which screens and menus each one gets |
| `security.py` | Password hashing and login tokens |
| `db.py` / `config.py` / `cache.py` | Database connection pool, settings from `.env`, an in-memory cache |
| `connectors.py` | The list of data sources the Data ingestion screen offers. Passwords and keys go to Databricks' secret store, never to Postgres |
| `reports/` | Regulatory return logic: the capital adequacy calculation, checks, and PDF/Excel export (with `exports.py`) |
| `ask/` | The "Ask a question" feature. A local AI model (Ollama, via `llm.py`) only *classifies* the question. `service.py` then checks it against a fixed list of approved queries (`catalogue.py`), so the model never writes SQL |
| `kpi_explain.py`, `recon_text.py` | Plain-English explanations of the headline ratios and of reconciliation differences |

**Routers (`routers/`)**, one per screen or feature:

| Router | Screen / purpose |
|---|---|
| `kpi` | Executive Summary (Screen 1) |
| `portfolio` | Portfolio & Credit Risk (Screen 2) |
| `reports` | Regulatory Reporting (Screen 3) |
| `scenario` | Scenario Modelling (Screen 4) |
| `performance` | Branch & Segment Performance (Screen 5) |
| `workflow` | Screen 6 extras: comments, audit trail and breaches (Camunda owns the tasks themselves) |
| `reconciliation` | Reconciliation tab and reconciliation tasks (the busiest, with 14 endpoints) |
| `ingestion` | Connect sources, upload files, start runs |
| `refresh` | Starts the Databricks job through its API (the "Refresh Now" button) |
| `ask`, `auth`, `health` | Question box, login, health check |

**Tests:** `backend/tests/` (pytest), with roughly one file per feature.

---

## 4. Frontend: `frontend/src/`

- **`App.jsx`**: page routes. **`auth.jsx`** + **`access.js`**: login and which role sees which
  page. **`api.js`**: the single HTTP client.
- **`pages/`**: one file per screen: `Dashboard`, `KpiDetail`, `Portfolio`, `Scenario`,
  `Performance`, `Reports`/`ReportView`, `Reconciliation`, `Tasks` (Screen 6), `Ingestion`, `Ask`,
  `AuditOversight`, `Login`.
- The calculations behind each screen live in plain JS modules, kept separate so they can be
  unit-tested:
  - `scenario/engine.js` recalculates the scenario in the browser on every slider move, with no
    database call.
  - `portfolio/derive.js` and `performance/derive.js` prepare the portfolio and branch figures.
  - `kpi/` holds the ratio settings, status thresholds and alert text.
- `workflow/tasklistApi.js` **calls Camunda Tasklist directly** to list and complete tasks.
- `components/`: shared charts, tiles and tables.
- Tests: `*.test.js(x)` next to the code (vitest, `npm test`).

---

## 5. Workflow: `camunda/`

- **`docker-compose.yaml`**: runs Zeebe, Elasticsearch and Tasklist. Operate is switched off to
  save memory.
- **`process/*.bpmn`**: the 3 approval processes:
  - `transaction-review`: fraud, compliance or operations review (also used for breaches)
  - `reconciliation-task`: the team decides each reconciliation item; the CFO approves important ones
  - `reconciliation-run-signoff`: the CFO signs off a whole run once every task is decided
- **`bridge/`**: small Python workers that connect Postgres and Camunda:
  - `poll_worker.py`: starts a review process for each new flagged row (Postgres → Camunda)
  - `outcome_worker.py`: writes each decision into `review_outcomes` (Camunda → Postgres)
  - `breach_check.py`: compares the latest ratios to limits and opens breach tasks
  - `deploy.py`: deploys the BPMN processes and forms
  - `*_db.py`: database helpers for each case type

---

## 6. Scripts and docs

- `scripts/run-local.ps1`: starts the app locally (also available as the `run-local` skill).
- `scripts/generate_synthetic_bank_data.py`: creates larger, clean test data for checking speed at
  scale.
- The `seed_*`, `plant_*_breaks.py` and `make_demo_cases.py` scripts set up demo data and
  deliberate differences for reconciliation demos.
- **Docs to read first:**
  1. `project-docs/Middle East bank data cleaning and reporting.md`: the source of truth.
  2. `project-docs/3-WEEK-POC-PLAN.md`: the plan currently being worked to.
  3. `specs/`: one spec per feature, each with its own acceptance criteria.

---

## Things to know as the new owner

- **Not everything is proven.** Several notebooks haven't been checked on a live Databricks
  cluster. The full Databricks job and the Camunda chain have run end-to-end once (2026-09-22).
  Screens 2-5 have tests but haven't been checked in a browser at bank-scale data.
- **Some numbers rest on placeholder assumptions.** NIM, cost-to-income, ROE and Compliance task
  routing use assumptions that someone with banking knowledge still needs to confirm.
- **Edit notebooks in Databricks, not locally.** The workflow is to edit and push from the
  Databricks Repo, then pull locally, so the copy in `notebooks/` can be overwritten.
- **Use `npm run` in `frontend/`.** Don't use `npx` there: the `&` in the folder name breaks
  Windows' command wrappers.
