# Regulatory Compliance Gaps — Current State and Demo Fixes

_7 October 2026 · Internal working document_

**Status:** the platform is a proof of concept and **does not currently meet** banking regulatory requirements,
either global (BCBS 239, ISO 27001 / SOC 2, NIST CSF) or Middle East (CBUAE / DFSA, SAMA + NCA, QCB, the
regional data protection laws). This document lists what is failing, why, how to fix it for production, and
which items can be fixed **for the demo only** with little effort.

> A demo fix makes the demo more credible. It does **not** make the platform compliant. Compliance is confirmed
> by the bank's own assessment against its regulator's rules, after the production fixes.

## How to read this

| Column | Meaning |
|---|---|
| **Pri** | **P1** blocks any regulated use · **P2** needed before go-live · **P3** expected, can follow |
| **Demo fix** | **Quick** under 1 hour · **Small** 1–4 hours · **Medium** half a day to a day · **No** not realistic for a demo (hosting, licences, or bank-side work) |

Fixes to notebooks need a pipeline re-run on Databricks to take effect, and should be made through the
Databricks Repo flow (edit in Databricks, push, pull locally), per `CLAUDE.md`.

---

## Already in line with regulatory expectations

- **Traceability (BCBS 239):** every reported number drills back to its formula, source table and record count.
- **Data-quality checks and reconciliation:** failed records are kept with the full original row, not dropped.
- **Maker-checker approvals** and a CFO sign-off on each run (Camunda).
- **Insert-only audit log:** triggers block UPDATE, DELETE and TRUNCATE (`db/schema.sql`).
- **Role-based access:** 7 roles checked on the server; the auditor role cannot write (`backend/app/roles.py`, `backend/app/main.py`).
- **Password storage:** PBKDF2-SHA256, 200,000 iterations, salted (`backend/app/security.py`).
- **Secrets in a vault:** Databricks secret scopes, never stored in Postgres (`backend/app/connectors.py`).
- **Local AI assistant:** no bank data is sent to an outside AI service.

---

## 1. Infrastructure

| # | What is failing | Evidence | Why it fails | Production fix | Pri | Demo fix |
|---|---|---|---|---|---|---|
| 1 | Data hosted outside the region (Neon on AWS; no Gulf region) | `backend/.env.example`, tech spec §11.2 | Data-residency rules (CBUAE, SAMA, QCB, PDPL) | Azure PostgreSQL + Databricks storage in UAE North / KSA | P1 | **No** |
| 2 | Cloud use not notified to / approved by the regulator | — | Regional outsourcing and cloud rules | Bank files the cloud-outsourcing notification | P1 | **No** (bank) |
| 3 | Camunda, API and bridge workers run on a developer laptop | `scripts/run-local.ps1`, `camunda/docker-compose.yaml` | Resilience and business continuity | Azure App Service, Camunda on AKS or a VM, supervised workers | P1 | **No** |
| 4 | No high availability or disaster recovery | Tech spec §8.3 | Business continuity | Zone-redundant PostgreSQL, backups, tested DR plan | P2 | **No** |
| 5 | No alerting or timeouts on pipeline runs; no central logs | `databricks.yml` has no `email_notifications` or `timeout_seconds` | Monitoring and incident detection | Job notifications + timeouts; Azure Monitor / Log Analytics | P2 | **Quick** — add `email_notifications` and `timeout_seconds` to `databricks.yml`, `databricks bundle deploy` |

## 2. Security

| # | What is failing | Evidence | Why it fails | Production fix | Pri | Demo fix |
|---|---|---|---|---|---|---|
| 6 | No MFA or single sign-on | `backend/app/routers/auth.py` (password only) | MFA mandatory for privileged / remote access | Entra ID or Keycloak with MFA | P1 | **Medium** — optional TOTP second step (e.g. `pyotp`) for demo users |
| 7 | Camunda security off: `ZEEBE_AUTHENTICATION_MODE=none`, Elasticsearch security off, Tasklist CSRF off, default `demo/demo` login — and that login is in the browser code | `camunda/docker-compose.yaml`, `frontend/src/workflow/tasklistApi.js` | No access control on the workflow engine | Camunda Identity, server-side Tasklist proxy in FastAPI, remove demo user | P1 | **No** (Identity/Keycloak setup is large) |
| 8 | Every logged-in user can see all groups' tasks in Tasklist; filtering is done in the browser | `frontend/src/workflow/tasklistApi.js` (comment and `CANDIDATE_GROUPS`), `pages/Tasks.jsx` | Least privilege, segregation of duties | Per-user Tasklist access via Identity; server-side filtering | P1 | **No** (already labelled in the UI with an assumption badge) |
| 9 | No database row-level security; who-sees-what is enforced only in the app | `db/schema.sql` lines 947-948 | Need-to-know access per country / entity | Postgres RLS or server-side scoping on every query | P2 | **Medium** — optional, for one table (e.g. customers by country) to show the pattern |
| 10 | 8-hour sessions; no logout or token revocation; token in `sessionStorage` | `backend/app/config.py` (`JWT_EXPIRE_MINUTES` default 480), `frontend/src/api.js` | Session-management controls | Short tokens + refresh, logout, revocation; HttpOnly cookies | P2 | **Quick** — set `JWT_EXPIRE_MINUTES=30` in `backend/.env`. **Small** — logout endpoint + revocation list |
| 11 | No rate limit or lockout on login | `backend/app/routers/auth.py` (only `/ask` is rate-limited) | Protection against password guessing | Rate limit + account lockout | P2 | **Quick** — reuse the `/ask` rate-limit pattern on `/auth/login` |
| 12 | `audit_log.ip_address` is never written; a database superuser can disable the audit triggers | `db/schema.sql` line 735; 12 `INSERT INTO audit_log` sites in `backend/app` | Audit records must be complete and tamper-evident | Record IP + user agent; export logs to write-once storage; restrict superuser | P2 | **Small** — capture IP in request middleware and write it at the 12 insert sites |
| 13 | SQL built with an f-string in the Neon ingestion notebook | `notebooks/multi_source_neon_ingestion.py` lines 289, 310 (D14) | SQL-injection risk | Parameterised query | P2 | **Quick** (needs a Databricks re-run to verify) |
| 14 | No penetration test, vulnerability or dependency scanning | `.github/workflows/` has only `databricks-sync.yml` | Vulnerability-management requirements | Annual pen test; scanning in CI | P2 | **Quick** — run `pip-audit` and `npm audit` once and record results; **Small** — add them as a GitHub Action. Pen test: **No** |

## 3. Data encryption

| # | What is failing | Evidence | Why it fails | Production fix | Pri | Demo fix |
|---|---|---|---|---|---|---|
| 15 | Browser → API over plain HTTP | Vite dev server on `http://localhost:5173` | Encryption in transit | HTTPS everywhere | P1 | **Quick** — self-signed HTTPS on the Vite dev server (e.g. `@vitejs/plugin-basic-ssl`); the browser will show a certificate warning |
| 16 | Camunda internal traffic unencrypted (gRPC, Elasticsearch HTTP) | `create_insecure_channel` in bridge workers; ES security off | Encryption in transit | TLS / mTLS, Elasticsearch security on | P1 | **No** |
| 17 | Encryption at rest uses provider-managed keys | Neon / Databricks defaults | Banks usually must control their keys | Customer-managed keys in Azure Key Vault | P2 | **No** |
| 18 | Customer personal data (names) shown and exported unmasked to every role that can see the screen | `customers.name`; API responses and exports | PDPL data minimisation | Masking / tokenisation; masked exports | P2 | **Small** — mask names in API responses and exports for roles that don't need them |
| — | Laptop disk encryption for local Elasticsearch data and logs not confirmed | — | Data at rest | n/a in production (no laptop) | P3 | **Quick** — confirm BitLocker is on |

## 4. Data accuracy and record-keeping (BCBS 239, regulatory reporting)

| # | What is failing | Evidence | Why it fails | Production fix | Pri | Demo fix |
|---|---|---|---|---|---|---|
| 19 | NIM, Cost-to-Income and ROE use placeholder assumptions | `specs/notebook-03-kpi-summary.md`; `AssumptionBadge.jsx` | Reported figures must follow approved definitions | Bank confirms formulas; remove placeholders | P1 | **No** (bank decision) — **Quick**: check every affected tile shows its assumption badge |
| 20a | Loan-ageing boundary: a loan exactly 30 / 60 / 90 / 180 days past due lands in the higher bucket (`<` should be `<=`) | `notebooks/06_portfolio_branch_scenario_snapshot.py` lines 250-257 (D1) | Accuracy | Fix the comparisons + test | P1 | **Quick** |
| 20b | Bekaa and Mount Lebanon missing from `REGION_CURRENCY`, so their costs drop out of cost-to-income and ROE | `notebooks/03_kpi_summary.py` line 55; Notebook 6 line 52 (D2) | Accuracy | Add the regions; align with the API's recompute | P1 | **Quick** |
| 20c | Monthly branch costs set against annual interest income | Notebook 3 lines 156-194; Notebook 6 (D3) | Accuracy | Use one period consistently | P1 | **Small** |
| 20d | `DUPLICATE_TRANSACTION` flags the original as well as the copy | `notebooks/05_fraud_business_rules.py` lines 233-255 (D4) | Accuracy | Flag only the later copy | P2 | **Quick** |
| 20e | Reconciliation tolerance in USD applied to native-currency balances | `notebooks/multi_source_reconciliation.py` line 61 (D13) | Accuracy | Convert before comparing | P2 | **Small** |
| 21 | Data-quality exception history is overwritten every run | Notebook 2 overwrite; tech spec §8.3 | Records must be kept for the retention period | Keep exceptions per run date (insert-only history) | P2 | **Medium** (schema, load and screens) |
| 22a | Null segment / channel / currency passes the checks | `notebooks/02_data_quality_verification.py` (D5) | Completeness | Flag nulls | P2 | **Quick** |
| 22b | No duplicate primary-key check; a duplicated ID rolls back the whole load | Notebook 2 (D6) | Integrity | Add a duplicate-key check | P2 | **Quick** |
| 22c | Load row counts verified after the commit | `notebooks/load_to_postgres.py` lines 338-380 (D7) | Integrity | Verify before committing | P2 | **Small** |
| 23 | FX failures not logged, only successes | `notebooks/fx_utils.py` (D18) | Complete audit of inputs used | Log failures | P3 | **Quick** |
| 24 | Never tested at bank volumes (largest run ~2,349 transactions) | Tech spec §4.5.4 | Capacity must be proven | Load test at real volumes | P2 | **Medium** — 100k / 1M synthetic run with timings |

## 5. Paperwork and process

| # | What is failing | Why it fails | Fix | Pri | Demo fix |
|---|---|---|---|---|---|
| 25 | No security, access, retention or change-management policies | Every framework requires documented policies | Write them or adopt the bank's | P2 | **Small** — short draft templates, clearly marked "draft" |
| 26 | Vendors not assessed; Camunda used under its non-production licence | Vendor / outsourcing risk; licence terms | Vendor risk assessment; Camunda Enterprise licence | P1 | **No** (commercial) |
| 27 | No independent assessment | Compliance has to be confirmed by an assessment | Gap assessment against the bank's regulator, then audit | P1 | **No** |
| 28 | No model-governance note for the AI assistant | Model risk expectations | One-page note: purpose, limits ("a signal, not a decision"), human review | P3 | **Quick** |

---

## Demo fixes — recommended set

All **Quick** items together are roughly **one day** of work; the **Small** items add about **two to three days**.
Times are estimates and exclude pipeline re-runs on Databricks.

### Quick (under 1 hour each)

| # | Fix | Where |
|---|---|---|
| 11 | Rate limit + lockout on login | `backend/app/routers/auth.py` |
| 10 | Shorter sessions (`JWT_EXPIRE_MINUTES=30`) | `backend/.env` |
| 5 | Failure emails and timeouts on the pipeline job | `databricks.yml` + `databricks bundle deploy` |
| 15 | HTTPS on the local site (self-signed) | `frontend/vite.config.js` |
| 13 | Parameterised SQL in the Neon notebook | `notebooks/multi_source_neon_ingestion.py` |
| 14 | One-off `pip-audit` / `npm audit` report | backend, bridge, frontend |
| 20a, 20b, 20d | Ageing boundary, missing regions, duplicate flagging | Notebooks 3, 5, 6 |
| 22a, 22b | Null checks, duplicate-key check | Notebook 2 |
| 23 | Log FX failures | `notebooks/fx_utils.py` |
| 19 | Confirm every placeholder KPI shows its assumption badge | frontend KPI tiles |
| 28 | AI assistant model-governance note | `project-docs/` |
| — | Confirm BitLocker on the demo laptop | Windows settings |

### Small (1–4 hours each)

| # | Fix | Where |
|---|---|---|
| 10 | Logout endpoint + token revocation | `backend/app/routers/auth.py`, `security.py`, frontend |
| 12 | Record IP address in the audit log | request middleware + 12 audit insert sites |
| 18 | Mask customer names for roles that don't need them | API responses + exports |
| 14 | `pip-audit` / `npm audit` in a GitHub Action | `.github/workflows/` |
| 20c, 20e, 22c | Period consistency, tolerance conversion, verify-before-commit | Notebooks 3, 6, reconciliation, load |
| 25 | Draft policy templates | `project-docs/` |

### Medium (optional, half a day to a day each)

| # | Fix |
|---|---|
| 6 | TOTP second step at login, to demonstrate MFA |
| 9 | Row-level security on one table, to demonstrate the pattern |
| 21 | Keep data-quality exception history per run |
| 24 | 100k / 1M load test with recorded timings |

---

## Not fixable for the demo — how to explain them

| Items | What to say |
|---|---|
| 1, 2, 3, 4 (hosting, residency, HA/DR) | "The demo runs locally. Production is Azure in-region with HA and DR; the bank notifies its regulator of the cloud use." |
| 7, 8, 16 (Camunda security) | "The workflow engine runs in its development mode for the demo. Production enables Camunda Identity, per-user access and TLS." |
| 17 (customer-managed keys) | "Production uses keys the bank controls, in Azure Key Vault." |
| 19 (placeholder KPIs) | "These three KPIs use documented placeholder assumptions until your finance team confirms the definitions." |
| 26, 27 (licence, vendor review, assessment) | "Compliance is confirmed through your own assessment; we'll support the vendor review and the Camunda licence." |

**One line for the client:** "The platform's core is built around regulatory principles — traceability, an
insert-only audit trail, reconciliation and approval controls. Production adds the in-region hosting, MFA,
encryption and resilience controls your regulator requires, followed by your compliance assessment."
