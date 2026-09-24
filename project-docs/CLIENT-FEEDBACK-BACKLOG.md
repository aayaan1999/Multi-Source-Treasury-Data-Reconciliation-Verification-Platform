# Client Feedback Backlog (CFO/COO review, 2026-09-23)

Eight points raised by the bank after the demo walkthrough, each broken into buildable tasks.
"Today" describes the app as of 2026-09-23 (checked against the code, not assumed).

**Legend**
- Size: **S** ≈ under a day · **M** ≈ 1-3 days · **L** ≈ a week or more
- **Bank input**: the task can be built with a clearly-labelled placeholder, but only becomes
  *real* once the bank supplies what's named. Placeholders get a UI footnote, same as the
  existing NIM / cost-to-income / ROE assumptions.
- Status: `todo` / `in progress` / `done` / `blocked (bank)`

**Suggested order:** 5 + 6 → 8 → 1 → 4 → 2 → 3 → 7 (reasoning at the end).

---

## 1. Automated reconciliation

> Reconciliation can't be done one by one manually. Filters needed; tasks created automatically.

**Today:** Reconciliation screen has type tabs + a status filter; each break is resolved alone in a
popup (Accept / Correct / Dismiss). No tasks are created - `backend/app/routers/reconciliation.py`
deliberately keeps it separate from Camunda. $1 numeric tolerance exists
(`notebooks/multi_source_reconciliation.py`, `NUMERIC_TOLERANCE_USD`).

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| REC-1 | More filters: entity type, field, size of difference, detected date, source system | S | - | todo |
| REC-2 | Bulk resolve: select many rows, one reason; still one `audit_log` row per exception | M | - | todo |
| REC-3 | Auto-rules by size: within tolerance → auto-accept (logged); key fields or large differences → task | M | Tolerances, which fields are material | todo |
| REC-4 | Group breaks into cases (per customer / per root cause) instead of one row per field | M | - | todo |
| REC-5 | Create Camunda tasks for material breaks (new flagCategory or route to Operations), reusing `poll_worker.py`'s tracking pattern | M | Which team owns reconciliation | todo |

**Done when:** a batch of hundreds of breaks can be triaged in minutes; only material ones reach a human, as tasks; every automatic decision is in the audit trail.

---

## 2. Source tracking & flow

> Record the source against each transaction; show a clear happy flow from Source X onwards.

**Today:** `transactions` has no source column (id, account, date, amount, currency, type, channel
only). `CLAUDE.md` already lists `source_system` + `transaction_code_mapping` as a blocked gap.
Five `multi_source_*` ingestion notebooks exist; only Neon is verified live.
`reconciliation_exceptions` does carry `source_system`.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| SRC-1 | Add `source_system` + `ingest_batch_id` (file/run reference) to every entity, from Notebook 1 through `load_to_postgres.py` into Neon | M | - | todo |
| SRC-2 | Show source on drill-downs (KPI detail, portfolio, task source record) | S | - | todo |
| SRC-3 | Lineage view: Source X file → raw → clean → Gold KPI → screen, with row counts and rejects per step | M | - | todo |
| SRC-4 | `transaction_code_mapping`: map each source's own transaction codes to our `type` | M | **Real code lists per source system** | blocked (bank) |
| SRC-5 | Verify the remaining 4 multi-source ingestions live (Mockaroo, IMF, Salesforce, Google Sheets) | M | - | todo |

**Done when:** any number on a screen can be traced to the source system, file and run it came from.

---

## 3. Entity deduplication ("Tata Consultancy" = "TCS")

> The same entity under different names must not be double-counted.

**Today:** nothing. Customers are matched only by exact `customer_id`; two records for one company
show as two exposures (top-20 exposures, concentration, segment totals).

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| DUP-1 | Name normalisation (drop Ltd / SAL / Pvt / Inc, case, punctuation) + known-abbreviation list | S | Abbreviation list (optional) | todo |
| DUP-2 | Candidate matching: fuzzy name + shared registration/tax ID, phone, address → `entity_match_candidates` | M | **A reliable ID, e.g. commercial registration no.** | todo |
| DUP-3 | Review queue: each candidate pair becomes a task; a human confirms or rejects (never auto-merge) | M | - | todo |
| DUP-4 | `master_entity_id` on customers; exposure/concentration aggregates group by it; originals untouched | M | - | todo |

**Done when:** confirmed duplicates roll up into one exposure; nothing is merged without a human decision.

---

## 4. Multi-currency: where do rates come from?

**Today:** `notebooks/fx_utils.py` fetches live rates from **open.er-api.com** (free, no key) at run
time; every fetch logged in `fx_rate_usage_log`; failure stops the run (no silent stale rate).
**Problems:** not an official rate; Lebanon has several LBP rates; every transaction is converted
at *today's* rate, not its own date's.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| FX-1 | Store daily rates by date (reuse `fx_rates` table/CSV) and convert each transaction at **its own date's** rate | M | - | todo |
| FX-2 | Pluggable rate source: bank's official feed / central bank, with the free API only as a labelled fallback | M | **Official source per currency** | blocked (bank) |
| FX-3 | Multiple LBP rates (official / market / platform) with a per-report choice of which one applies | M | **Which LBP rate for which report** | blocked (bank) |
| FX-4 | Show rate + source + date used on KPI detail and exports | S | - | todo |

**Done when:** every converted figure states which rate, from where, for which date.

---

## 5. Fraud vs "a rule was exceeded"

> What makes something fraud? An amount over a limit is NOT fraud - find other such examples.

**Today:** `notebooks/05_fraud_business_rules.py` - `LARGE_AMOUNT`, `VELOCITY_BREACH`,
`STRUCTURING_PATTERN` are all labelled FRAUD; `DUPLICATE_TRANSACTION` is FAULT.
Correct reading: large amount = **threshold/reporting event**; velocity = **unusual activity**;
structuring = **genuine AML red flag**; duplicate = **operational fault**.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| FRD-1 | Reclassify flags into **THRESHOLD** (reporting) / **SUSPICIOUS** (AML or fraud pattern) / **OPERATIONAL**; update routing + UI labels | S | - | todo |
| FRD-2 | New suspicious patterns possible with current data: dormant account reactivated; pass-through (in and out same day); activity too big for segment; many round amounts; splitting across a customer's accounts | M | - | todo |
| FRD-3 | Thresholds and typologies from config, not hard-coded constants | S | **Bank's AML typologies + reporting thresholds** | todo |
| FRD-4 | Real fraud signals (account takeover, new device/IP, new beneficiary) - future Notebook 7 | L | **Device/login/beneficiary data** | blocked (bank) |

**Done when:** nothing is called "fraud" just for being large; each flag says *why* it's suspicious.

---

## 6. Task logic: when is a task created?

**Today:** every data-quality exception and every flagged transaction becomes its **own** task
(`camunda/bridge/poll_worker.py`), plus one per breach (`breach_check.py`). Routing: FRAUD →
fraud-investigation; capital/liquidity/FX data issues → compliance; rest → operations.
**Problems:** one task per flag, not per case (a 4-transaction velocity breach = 4 tasks); one
transaction hit by two rules = two tasks; no priority, severity or due date; reconciliation creates none.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| TSK-1 | Case grouping: one task per account + day (or per pattern) listing all related flags | M | - | todo |
| TSK-2 | Severity score per case; only above a threshold becomes a task, the rest go to a daily digest | M | Severity rules | todo |
| TSK-3 | Due date by severity/team; overdue badge on Tasks and Audit & Oversight | S | **SLA per team** | todo |
| TSK-4 | Written task-creation policy (what, who, how fast) shown in the UI | S | **Sign-off** | todo |

**Done when:** the queue holds cases, not raw flags, each with a priority and a deadline.

---

## 7. Conversational reporting

> A chat box in Reports: "Give me the report for X, Y, Z" → a table.

**Today:** nothing. No AI model is connected. Reports has fixed views with PDF/Excel export and an
insert-only `audit_log`.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| CHT-1 | Catalogue of approved, read-only query "tools" (KPIs, report lines, portfolio/branch aggregates) with allowed filters | M | Which reports it must answer | todo |
| CHT-2 | Backend endpoint: the model only picks a tool + filters; the table is filled **straight from the query result**, never from model text; read-only DB role | L | **Approval to send data to an external AI service** | blocked (bank) |
| CHT-3 | Answer panel: table, "data used / filters used", Excel export (reuse existing export) | M | - | todo |
| CHT-4 | Every question, tool, filters and row count written to `audit_log` | S | - | todo |
| CHT-5 | Guardrail: numbers in the model's text checked against the table; "can't answer from approved data" instead of guessing | M | - | todo |

**Done when:** a question returns an exportable table whose every number came from the database, with its sources shown and the request audited.

---

## 8. Breach marking: when is something a breach?

**Today:** `limits` (KPI, threshold, direction) + `breach_check.py` compares the latest KPI; a new
breach creates a Compliance task. Two **placeholder** limits set 2026-09-23: capital ratio below
12.5%, NPL above 5%. Dashboard tiles hold a **separate copy** of thresholds in
`frontend/src/kpi/kpiConfig.js`, which can drift from `limits`.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| BRC-1 | Three levels per limit: regulatory minimum / internal risk appetite / early warning (early warning = notification, not a task) | M | **Official values per level** | todo |
| BRC-2 | Consecutive-days rule per limit (e.g. breached 3 days running) in `breach_check.py` | S | **Rule per limit** | todo |
| BRC-3 | Deadline from `resolution_days`; due date + overdue shown on breach tasks and Audit & Oversight | S | Deadlines | todo |
| BRC-4 | Tiles read thresholds from `limits` via the API - one source of truth, remove the copy in `kpiConfig.js` | M | - | todo |

**Done when:** the bank's own limits drive both the tiles and the breach tasks, at the right level, with deadlines.

---

## Why this order

1. **5 + 6** - relabelling rules and grouping flags into cases makes the Tasks screen credible
   right away; no bank input needed to start.
2. **8** - small, and the structure can go in with placeholders.
3. **1** - builds on 6's case grouping for reconciliation tasks.
4. **4 → 2 → 3** - each needs a bank input (official FX source, source-system code lists,
   registration IDs) to be real.
5. **7** - largest, and gated on the bank's decision about external AI.

## Waiting on the bank (collected)

- Official limits per level, consecutive-days rule and deadlines (BRC-1/2/3)
- AML typologies and reporting thresholds (FRD-3); device/login/beneficiary data (FRD-4)
- SLAs per team and task-creation sign-off (TSK-3/4)
- Reconciliation tolerances, material fields, owning team (REC-3/5)
- Official FX source per currency; which LBP rate per report (FX-2/3)
- Source-system list and transaction-code lists (SRC-4)
- A reliable company identifier (DUP-2)
- Approval to use an external AI service; list of reports for chat (CHT-1/2)
