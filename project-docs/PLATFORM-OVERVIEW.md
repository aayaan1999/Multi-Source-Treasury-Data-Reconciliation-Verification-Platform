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

## Getting started (new team member)

This section is the short version. The full steps are in the documents it links to; follow those
when they disagree with this summary.

### Step 1: get access (ask the project owner)

No document can give you these. Ask for each one you need:

| Access | Needed for | Where it goes |
|---|---|---|
| **App database** (Neon connection string) | Running the app at all | `DATABASE_URL` in `backend/.env` |
| **Databricks workspace** + personal token | Running or deploying the data pipeline, the Refresh Now button | `DATABRICKS_HOST` / `DATABRICKS_TOKEN` in `backend/.env`; `databricks auth login` for the CLI |
| Core banking Neon project, Supabase loan API, Salesforce | Only for the reconciliation sources | Connected from the app's **Data ingestion** tab (stored in the Databricks secret scope, never in Postgres) |
| Ollama (or another OpenAI-compatible server) | Only for the **Ask** screen | `LLM_BASE_URL` / `LLM_MODEL` in `backend/.env` |

Never paste these values into chat, commits or `.env.example`; `.env.example` is committed and the
repo is public.

### Step 2: install and run the app

Full steps: the `setup-new-machine` skill (`.claude/skills/setup-new-machine/SKILL.md`) and
`project-docs/PREREQUISITES.md`. In short:

1. Install Git, **Python 3.10+**, Node.js, and Docker Desktop (Docker is only needed for Camunda).
2. Backend: `cd backend`, create `.venv`, `pip install -r requirements.txt`, copy `.env.example` to
   `.env` and fill in `DATABASE_URL` (direct host, no `-pooler`, ending `?sslmode=require`) and
   `JWT_SECRET`.
3. Frontend: `cd frontend`, `npm install`.
4. Demo users (once per database, safe to re-run): `backend\.venv\Scripts\python.exe backend\seed_demo_users.py`.
5. Start: `scripts\run-local.ps1` starts the backend (`http://127.0.0.1:8000`, API docs at
   `/docs`) and the site (`http://localhost:5173`) with no extra windows. `-NoBrowser` skips opening
   the browser; `-Stop` stops everything.
6. Optional, for the Tasks and Audit & Oversight screens: start Docker Desktop, run
   `docker compose up -d` in `camunda/`, then `python camunda/bridge/deploy.py` once. Run
   `run-local.ps1` again and it starts the three bridge workers too.

If the dashboard says there are no numbers yet, the Databricks pipeline hasn't loaded the
database. The app itself is working.

### Step 3: log in as each role

`seed_demo_users.py` creates seven users. Their passwords are listed in `specs/user-roles.md`, and
the login page lists the users. Each role lands on a different home screen:

| User | Role | Home screen |
|---|---|---|
| `cfo@bankx.demo` | CFO (approves, signs off) | Executive Summary |
| `cro@bankx.demo` | CRO (risk, breach tasks) | Portfolio |
| `recon.analyst@bankx.demo` | Reconciliation Analyst | Tasks |
| `reporting@bankx.demo` | Reporting Officer | Reports |
| `compliance@bankx.demo` | Compliance Officer (fraud tasks) | Tasks |
| `auditor@bankx.demo` | Internal Auditor (read-only) | Audit & Oversight |
| `admin@bankx.demo` | Platform Admin | Data ingestion |

`project-docs/DEMO-GUIDE.md` walks through the demo story screen by screen.

### Step 4: everyday commands

| Task | Command |
|---|---|
| Backend tests | `cd backend; .\.venv\Scripts\python.exe -m pytest` |
| Frontend tests | `cd frontend; npm test` |
| Frontend dev server only | `cd frontend; npm run dev` (always `npm run`, never `npx`) |
| Apply a database migration | `backend\.venv\Scripts\python.exe db\apply_migration.py db\migrations\<file>.sql` |
| Deploy the Databricks job | `databricks bundle validate`, then `databricks bundle deploy` from the repo root (see `project-docs/DATABRICKS-SETUP.md`) |
| Run the pipeline now | **Run now** in the Databricks Workflows UI, or the **Refresh Now** button in the app |

### Step 5: how work is done here

1. **Spec first.** Every feature has a spec in `specs/`. Write or update it before or alongside
   the code, including acceptance criteria. Mark anything not checked for real (for example "not
   run on a live cluster") instead of claiming it passes.
2. **Tests with the change.** Backend changes come with pytest tests, frontend changes with vitest
   tests next to the file.
3. **Database changes go in a new numbered migration** in `db/migrations/`. Never edit an old one.
4. **Notebooks are edited in Databricks**, pushed to GitHub from there, then pulled locally. Don't
   edit `notebooks/` locally at the same time.
5. **Check scope against `3-WEEK-POC-PLAN.md`** before building anything from
   `PLATFORM-BUILD-PLAN.md`.
6. Commits go to `main`, with a message that says what changed and why (see `git log` for the style).

### Step 6: what to read, in order

1. This file: the map.
2. `CLAUDE.md`: the current state of each part and the house rules.
3. `project-docs/3-WEEK-POC-PLAN.md`: what's in scope now.
4. `project-docs/Middle East bank data cleaning and reporting.md`: the source of truth, including
   the banking terms (CAR, LCR, NPL, IFRS 9 staging). Read the parts for the area you're working on.
5. The spec in `specs/` for whatever you're about to change.
6. `project-docs/PLATFORM-TECHNICAL-SPECIFICATION.md`: the full technical reference, for depth.

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

---

## Architecture deep-dive

Written 2026-10-13 from reading the code, without running it. "Fragile" below means large files
with a lot of logic packed in, not a measured complexity score.

### 1. Entry points and the main data flow

**Entry points:**
- `backend/app/main.py`: the FastAPI app.
- `frontend/src/main.jsx` → `App.jsx`: the React app.
- `databricks.yml`: the Databricks job (14 steps).
- `camunda/bridge/poll_worker.py`, `outcome_worker.py` and `breach_check.py`: three long-running
  workers.
- `scripts/run-local.ps1`: starts everything locally.

**How one flagged item travels from data to decision** (for example, a suspicious transaction or
a reconciliation difference):

1. A file arrives in the Databricks landing folder. It gets there from a source system, or from an
   upload on the Ingestion screen (`POST /ingestion/upload` checks the CSV, then copies it there).
2. The job runs: ingest → data-quality checks → fraud rules and reconciliation →
   `load_to_postgres.py`. That last step merges everything into Neon in one transaction, and it
   never overwrites a review `status` a person has set.
3. `poll_worker.py` finds new flagged rows that have no `camunda_process_tracking` entry yet. For
   each one it starts a Camunda process routed to the right group (fraud, compliance or
   operations), then records the process so the same row is never started twice.
4. In the browser, the Tasks screen calls **Camunda Tasklist directly**
   (`frontend/src/workflow/tasklistApi.js`), not through the backend. The backend only adds the
   full source record, comments and the audit trail (`routers/workflow.py`,
   `routers/reconciliation.py`).
5. When a person completes a task, Camunda creates a job. `outcome_worker.py` picks it up and
   writes the decision to Postgres (`review_outcomes`, the `recon_*` tables). Rule violations, such
   as someone approving their own decision, are sent back to the person as a task instead of
   failing.

**Document handling:** PDF and Excel exports are built in `backend/app/reports/documents.py`
(ReportLab and openpyxl, both using the same number formatting).

**Masking: none exists yet.** Customer names are currently shown unmasked to every role. Masking
is planned in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`, items ENC-4 and ENC-5, scheduled for
14 Oct and not built.

### 2. Where state lives, and authentication

- **Data that persists:** Postgres on Neon. **Workflow state:** Camunda. The link between the two
  is the `camunda_process_tracking` table.
- **Backend login:** each request carries a signed token (JWT, HS256) checked in `security.py`.
  Passwords are stored as PBKDF2 hashes. There are no server-side sessions.
- **Who can see what:** one table in `roles.py`. `main.py` applies two checks to every router:
  `screen(...)` returns 403 if the role doesn't have that screen, and `no_writes_for_read_only`
  blocks the auditor from changing anything.
- **Frontend:** a single React context (`auth.jsx`); there is no Redux. The login is kept per
  browser tab (`sessionStorage`), and any 401 signs the user out.
  - `api.js` refuses to send a request if the stored login has changed to a different person.
  - Tasklist uses its own separate session cookie.
- **Caches:** `cache.py` holds in-memory data per backend process, so it's lost on restart and not
  shared if you run more than one backend. KPI explanations are cached per pipeline run.

### 3. Outside services and how failures are handled

| Service | Configured in | What happens when it fails |
|---|---|---|
| Neon Postgres | `DATABASE_URL`, `db.py` | 30 s connect timeout, keepalives, **one retry** on a dropped connection (and idle connections are discarded, because Neon sleeps). Still failing → 503 |
| Databricks Jobs API | `DATABRICKS_HOST` / `TOKEN` / `JOB_ID`, `routers/refresh.py` | 20 s timeout → 502 with Databricks' own message. Not configured → 503 |
| Databricks Files (uploads) | `routers/ingestion.py` | 120 s timeout |
| Camunda Zeebe (gRPC) | `ZEEBE_ADDRESS`, `camunda/.env` | 45 s per call. A failed pass is retried on the next poll (every 5 min). The connection is unencrypted |
| Camunda Tasklist | Proxied by Vite at `/tasklist`, `VITE_TASKLIST_*` | One retry after logging in again on a 401. Other errors are shown to the user. **The login is the default demo/demo, and it ships in the browser code** |
| Ollama (Ask, KPI explanations) | `LLM_*`, `ask/llm.py` | 90 s timeout. Ask returns 503; KPI explanations fall back to fixed wording and try the model again later |
| Source connectors | `connectors.py` | 10–15 s timeouts. Passwords and keys go to the Databricks secret store, never to Postgres |

Nothing has a circuit breaker or exponential backoff. Retries are a single extra attempt, or the
next scheduled pass.

### 4. Fragile zones

1. **`notebooks/load_to_postgres.py`**: each table group has its own merge rule. The riskiest is
   that `flagged_transactions` only ever inserts, so it never resets a status a reviewer set.
   Getting a rule wrong either wipes people's decisions or leaves stale rows behind.
2. **`camunda/bridge/poll_worker.py` plus `recon_runs_db.py` / `recon_tasks_db.py`**: these decide
   when processes start, when old reviews are cancelled because a newer run replaced them, when a
   run is ready for sign-off, carry-over, escalation after three carries, and send-back. A bug here
   creates duplicate tasks or lost tasks. The duplicate protection depends on the tracking table's
   `ON CONFLICT` key.
3. **`backend/app/ask/service.py` + `extract.py`**: rules for combining what the AI model guessed
   with what the code read directly from the question. These are the safety net that stops a wrong
   model answer. Change them only alongside the question test sets in
   `backend/tests/ask_questions*.json`.
4. **`frontend/src/pages/Tasks.jsx` + `ReconTaskPanel.jsx`**: the two largest UI files. They depend
   on Tasklist's exact request shapes: `/assign`, not `/claim`, and variables sent as a list of
   `{name, value}` pairs.

One easy-to-miss trap: on Windows, the bridge workers must build their Zeebe connection inside the
running event loop. `camunda/bridge/_env.py` sets the Windows event-loop policy so this works.

### 5. Error handling and diagnostics

- **Backend:** `main.py` turns database errors into 503s: a missing table or column gets a message
  telling you to run a migration, and an unreachable database gets "Database unavailable". The
  routers raise explicit HTTP errors (mostly 400, 404 and 409; also 422, 503, 502, 403, and one
  429).
- **Logging is the weak spot.** Only `main.py` logs, and only database outages. The bridge workers
  use `print`. There are no request IDs, no structured logs and no metrics. The `/health` endpoint
  reports whether the database is reachable.
- **Environment variables needed to start from scratch:**
  - `backend/.env`:
    - **Required:** `DATABASE_URL` and `JWT_SECRET`.
    - **Optional:**
      - `JWT_EXPIRE_MINUTES`, `CORS_ORIGINS`, `DB_POOL_MAX`
      - `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_JOB_ID`
      - `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS`
  - `camunda/.env`: image versions, `ZEEBE_AUTHENTICATION_MODE`, client ID and secret.
  - `camunda/bridge/.env`: `ZEEBE_ADDRESS`. The workers reuse `DATABASE_URL` from `backend/.env`.
  - `frontend/.env`: `VITE_API_URL`, `VITE_BANK_NAME`, `VITE_DEV_API_TARGET`.
  - In Databricks: a secret scope `neon` with `host`, `database`, `user` and `password`, plus the
    `bank-data-sources` scope.

**Biggest production gaps:**
- No masking.
- Demo Tasklist login and an unencrypted Zeebe connection.
- In-memory caches that only work with a single backend process.
- Thin logging.
