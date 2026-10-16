# Platform Ownership Walkthrough: Notes from 3 Days

**Purpose:** what I covered while taking ownership of the platform (14-16 October 2026), so I can explain
each feature, guide developers, and know what is real, what is a placeholder, and what is not built yet.

**How the platform fits together (one line):** source files and systems → **Databricks** (clean, check,
calculate overnight) → **Neon Postgres** → **FastAPI** backend → **React** screens, with **Camunda** running
the review and approval tasks.

**How to trace any number:** Screen (`frontend/src/pages/…jsx`) → API (`backend/app/routers/…py`) →
summary table in Neon → the notebook that built it (`notebooks/…py`).

---

## Day 1 (14 Oct): Getting data in

| Topic | What I learned |
|---|---|
| **Data ingestion tab** | The first screen in the menu: sources connected, files in the latest run, records received / kept / held back, failed loads. Built from real pipeline results once a run exists; "Scheduled pulls" is still demo content |
| **Connectors** | Six connector types (core banking files, Salesforce, PostgreSQL, REST API, AWS S3, Snowflake). Real today: core banking CSVs, a second Neon database standing in for core banking, a Supabase REST API standing in for the loan system, and Salesforce. "Test connection" really connects only for PostgreSQL and REST API |
| **File uploads** | CFO and Admin only. Only the 8 known CSVs are accepted, checked in the browser and again on the server (name, size up to 100 MB, required columns). A file that would remove more than 20% of existing customers, accounts, loans or branches asks for confirmation first. Each upload writes an audit row |
| **The 14-step job** (`databricks.yml`) | ingest → quality → KPI summary, exception summary, fraud rules, portfolio snapshot, pipeline reconciliation → Salesforce / core banking / loan API ingest and reconciliation → load to Postgres. It starts on file arrival (about 2 minutes after the last file) or with "Run All Sources" |
| **Load to Postgres merge rules** (`notebooks/load_to_postgres.py`) | Everything loads in **one transaction**, so a screen never shows a half-loaded state. Entity tables are fully refreshed; Gold tables replace the latest day only; `flagged_transactions` is **insert-only and never overwrites a reviewer's status**; reconciliation breaks keep their status, and a resolved break that reappears is reopened |

---

## Day 2 (15 Oct): The screens

| Topic | What I learned |
|---|---|
| **1. Executive Summary** | 8 KPI tiles calculated overnight by Notebook 3 into `kpi_daily_summary`. Calculated directly: CAR, LCR, NPL, total assets, dollarization. **Built on placeholder assumptions:** NIM (deposit rates), cost-to-income (branch-cost currency), ROE (Tier 1 used as equity), each marked with an "Assumption" button. Limits have three levels (early warning, internal limit, regulatory), and crossing one creates a task. The alert strip writes 3-5 plain sentences. The AI only rewords text the code wrote and never produces a number |
| **2. Portfolio, Branch, Scenario** | All read small summary tables from Notebook 6 (the 2-second load rule). Portfolio shows two bars per category (total and bad loans), IFRS 9 stages, top exposures (25% limit), ageing and LTV. Branch shows the league table, regions, segments (**profit is an estimate: cost is split proportionally**), products, channels and the efficiency quadrant. Scenario uses 4 sliders and presets; it fetches about 50 numbers once and then **calculates in the browser**, with an Assumptions panel listing every rule |
| **3. Regulatory Reporting** | One template (Capital Adequacy). The report calendar holds example rows. **Drill-to-source** opens every number back to its formula, source table and record count. Validation checks block submission. PDF and Excel export |
| **4. Report Workflow and audit trail** | Flagged item → Camunda task → right team → decision → saved back to the database. `audit_log` is **insert-only**: the database refuses edits and deletes, which is what makes it trustworthy |
| **5. Data quality checks** (Notebook 2) | 27 checks across 8 tables. Good rows go to `*_clean`; bad rows go to `data_quality_exceptions` with a reason. Users see them as tasks (Operations, or Compliance for capital and liquidity data), on the Reconciliation tab, and in the AI assistant |

---

## Day 3 (16 Oct): Workflow, reconciliation and access

| Topic | What I learned |
|---|---|
| **1. Fraud flag → Camunda task** | Notebook 5 runs 9 rules and labels each flag **Threshold** (a limit crossed, which is not fraud), **Suspicious** or **Operational**. Thresholds live in `app_settings`. The bridge (`poll_worker.py`, every 5 minutes) groups flags by account, day and type into **one case**, scores the severity (Low goes to a daily digest), sets a deadline and routes it: Suspicious → Fraud, Threshold → Compliance, Operational → Operations |
| **2. Reviewer decisions** | Approve / Reject / Corrected, **always with a comment**. Stored in three places: Camunda (authoritative), `audit_log` (permanent) and `review_outcomes` (data). The record's status updates immediately. **Gap:** nothing reads `review_outcomes` back into Databricks yet, so corrections don't change the numbers. Added to the backlog as **FLOW-7** |
| **3. Reconciliation tab** | Two checks: **pipeline** (did our cleaning lose anything: rows and amounts per currency, received vs kept) and **source systems** (our data vs core banking, the loan system and Salesforce). Noise is cleared automatically (under $1, formatting-only). Breaks are grouped by cause; important ones get their own task; 20+ missing records at once become one "check the file" task. Three levels: team decides → CFO approves important ones and any fix → CFO signs off the run, never the same person. We **never write to the bank's systems**; approved fixes are re-applied to our copy each run |
| **4. Roles and access** | 7 demo users (CFO, CRO, Reconciliation Analyst, Reporting Officer, Compliance Officer, Internal Auditor, Admin), each with their own home screen, menu and tasks, all from one table (`backend/app/roles.py`). The server refuses data for screens a role doesn't have, and the auditor can change nothing |

---

## Key files by area

| Area | Files |
|---|---|
| Pipeline | `notebooks/01…06_*.py`, `pipeline_reconciliation.py`, `multi_source_reconciliation.py`, `load_to_postgres.py`, `fx_utils.py`, `databricks.yml` |
| Backend | `backend/app/main.py`; `routers/` (kpi, portfolio, performance, scenario, reports, workflow, reconciliation, ingestion, auth); `roles.py`, `security.py`, `kpi_explain.py`, `reports/` |
| Frontend | `frontend/src/pages/` (Dashboard, KpiDetail, Portfolio, Performance, Scenario, Reports, ReportView, Tasks, Reconciliation, Ingestion, AuditOversight); `scenario/engine.js`, `kpi/kpiConfig.js`, `workflow/tasklistApi.js`, `access.js` |
| Camunda | `camunda/process/*.bpmn`; `camunda/bridge/poll_worker.py`, `outcome_worker.py`, `breach_check.py`, `cases_db.py`, `recon_*_db.py`; `camunda/docker-compose.yaml` |
| Database | `db/schema.sql`, `db/migrations/001-023`, `db/apply_migration.py` |
| Specs | `specs/` (one per feature); `project-docs/CLIENT-FEEDBACK-BACKLOG.md` for the work list |

---

## Status: what is proven and what is not

**Verified live:**
- the Databricks job deploy and the full ingest → load chain (22 Sep)
- the Camunda chain: flag → task → decision → database, including breach tasks (22 Sep)
- the reconciliation approval chain on the local stack (30 Sep)
- Salesforce reconciliation (29 Sep)
- core banking and loan API reconciliation (8 Oct)

**Not yet proven:**
- Notebook 2, 3 and 5 outputs have not been compared against their expected values
- the screens have only run on small sample data (6-10 rows per table); there has been no bank-scale or speed test
- several screens have not been checked in a browser against realistic data
- a CFO-approved correction being re-applied by Notebook 1 (FLOW-5b) has never run live

**Placeholders the bank must confirm:**
- the KPI assumptions (deposit rates, region currencies, Tier 1 used as equity) and all KPI limits
- the 25% single-borrower limit, the segment cost split and the fixed/floating rate maps
- the scenario presets and the devaluation → default rule
- the fraud thresholds, task severity and deadlines, and team routing
- the reconciliation thresholds (10,000 important, $1 tolerance, 20 missing), the 8:00 cut-off and the 3-carry escalation

**Not built yet:**
- trend charts and stage migration (need history), cost of risk, and prior-period comparison
- the report approval workflow (the Reporting Officer's task list is empty) and more report templates
- read-back of review decisions into Databricks (FLOW-7) and a timed nightly schedule
- Mockaroo reconciliation, and real source-code mapping (needs the bank's code lists)

---

## Things to watch for future development

1. **Never calculate on page load:** calculate in a notebook into a summary table; screens only read.
2. **Scenario maths stays in the browser.**
3. **`audit_log` is insert-only:** never add edit or delete paths.
4. **The AI never produces a number.**
5. **There is one limits table:** tiles and breach tasks read the same values.
6. **Every new placeholder needs a visible label** on screen.
7. **Edit notebooks in Databricks**, not locally at the same time.
8. **Database changes are numbered migrations**, applied to Neon in order.
9. **Before production:**
   - no data masking yet (backlog section 10)
   - demo login (token stored in the browser) and a shared Camunda Tasklist login with no per-person access
   - in-process caches and thin logging
   - no TLS on Camunda
   - demo passwords in a public repository
   - a possible duplicate Camunda task if starting a process times out and is retried
10. **Windows:** always `npm run …`, never `npx vite` (the `&` in the folder name breaks it).

**Recommended next priorities:** bank-scale test data and a speed check → compare the notebook outputs →
confirm the placeholders with the bank → add a nightly schedule → production hardening.

---

## Questions my manager may ask (short answers)

| Question | Answer |
|---|---|
| Why does cost-to-income show 345%? | The sample data is tiny (little income against full branch costs) and the figure rests on a placeholder. It is not a calculation error |
| Is a 60,000 USD payment fraud? | No. It is a Threshold flag, a reporting matter that goes to Compliance |
| Do reviewer corrections update the dashboards? | Not yet. They are stored but not read back into the numbers (FLOW-7). Once built, they will show after the next nightly run, never instantly |
| Can anyone change the audit trail? | No. The database only allows new rows to be added |
| Do we change the bank's core system when fixing a break? | No. We only fix our own copy, after CFO approval |
| Is it production-ready? | No. It needs masking, real login, hosting, logging, Camunda security and bank-scale testing |
| What is the biggest risk? | Nothing has been tested at bank scale, and many figures rest on placeholders the bank hasn't confirmed |

---

## Open follow-ups

- **ING-8** and **FLOW-7** are added to `project-docs/CLIENT-FEEDBACK-BACKLOG.md` but not committed yet.
- **File-arrival wait time:** CLAUDE.md says 10 minutes, but `databricks.yml` uses 120 seconds. Update CLAUDE.md.
- **No timed nightly schedule** exists; the job only runs on file arrival or a manual run.
- **Out-of-date documents:**
  - several spec "Status" lines still say "not yet implemented" for built features
  - CLAUDE.md still calls Salesforce reconciliation "spec only"

---

## 30-minute team walkthrough (outline)

| Time | Section |
|---|---|
| 0-3 min | What the platform is and the one-line architecture |
| 3-8 min | Day 1: how data gets in (ingestion tab, connectors, uploads, the 14-step job, load rules) |
| 8-18 min | Day 2: the screens (KPIs, portfolio / branch / scenario, reporting with drill-to-source, workflow and audit trail, data quality) |
| 18-25 min | Day 3: fraud flags to tasks, reviewer decisions, reconciliation and approvals, roles |
| 25-30 min | What is proven vs not, the placeholders, next priorities, questions |
