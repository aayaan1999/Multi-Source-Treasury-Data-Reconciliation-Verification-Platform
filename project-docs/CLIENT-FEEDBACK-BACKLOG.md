# Client Feedback Backlog (CFO/COO review, 2026-09-23)

Eight points raised by the bank after the demo walkthrough, each broken into buildable tasks.
"Today" describes the app as of 2026-09-23 (checked against the code, not assumed).

**Legend**
- Size: **S** ≈ under a day · **M** ≈ 1-3 days · **L** ≈ a week or more
- **Bank input**: the task can be built with a clearly-labelled placeholder, but only becomes
  *real* once the bank supplies what's named. Placeholders get a UI footnote, same as the
  existing NIM / cost-to-income / ROE assumptions.
- Status: `todo` / `in progress` / `done` / `blocked (bank)`

**Priority (updated 2026-09-24):** the **target end-to-end flow** below comes first:
FLOW-1a → FLOW-3 → FLOW-5 → FLOW-6 → FLOW-4 → FLOW-1b/1c. The eight client points follow, in the
order 5 + 6 → 8 → 1 → 7 → 4 → 2 → 3 (reasoning at the end; 7 moved up on 2026-09-24 when the chatbot
became rule-based and stopped waiting on external-AI approval).

**Open scope question:** these tasks go beyond `3-WEEK-POC-PLAN.md`, the plan currently being
executed. Decide whether they replace its remaining work or follow it before starting.

---

## Target end-to-end flow (finalised with Ankit Sir, 2026-09-24)

1. **Data collection:** 10 countries, each with its own source systems (ERP, CRM, ...), gathered
   automatically into Databricks.
2. **Processing and health checks:** cleaning, duplicate and fraud checks → one clean, standard dataset.
3. **Reconciliation:** when data changes or drops during cleaning (e.g. a raw total of ₹20,000
   becomes ₹15,000 after checks), the gap is flagged as an item on the Reconciliation tab.
4. **CFO dashboard:** aggregated KPIs and a global financial summary across all 10 countries.
5. **Task assignment and approval:** the CFO investigates, handles the item directly or reassigns
   it; the assignee updates values, comments and submits back; the CFO gives final approval and
   the database updates.
6. **Refresh:** data refreshes automatically every 24 hours, plus a "Refresh Now" button to update
   after reconciliation without waiting for the daily cycle.

**Reconciliation is per source.** A *source* is one system that sends data (e.g. "Lebanon ERP",
"Lebanon CRM", "KSA ERP"); a *country* is only a tag on each source, used for dashboards,
filtering and routing, never the unit of reconciliation. For each source, data type and run, the
row count and amount total are compared as received vs after cleaning; a gap becomes **one item**
(not one per record) that opens onto the exact rejected records and why:

| Source | Data | Received | After cleaning | Gap | Result |
|---|---|---|---|---|---|
| Lebanon ERP | transactions, 24 Sept | ₹20,000 (500 rows) | ₹15,000 (488 rows) | ₹5,000 (12 rows) | Item on the Reconciliation tab |
| KSA ERP | transactions, 24 Sept | ₹80,000 (1,200 rows) | ₹80,000 (1,200 rows) | none | nothing to do |

This **pipeline reconciliation** (did our own pipeline lose or change anything?) is different from
point 1's **source reconciliation** (does our copy match the bank's core system?). Recommendation:
both, since they catch different problems; point 1 stays as the second kind, pending confirmation.

**Gap analysis (current system vs the flow):**

| Step | Fits today? | Work needed |
|---|---|---|
| 1. Collection | Partly: one CSV set; 5 demo connectors, only Neon verified | Connector + field/code mapping per source; source and country tag on every record; completeness check (did every source deliver?) |
| 2. Health checks | Yes (Notebooks 2 and 5) | Run per source; duplicate-company matching (point 3) |
| 3. Reconciliation | **No: different kind** | Control totals per source at received / loaded / clean; items on the tab linked to the rejected records |
| 4. CFO dashboard | Yes (Executive Summary) | Country breakdown; one reporting currency for global totals |
| 5. CFO workflow | **No: tasks go to teams, single review step, shared Camunda login** | New Camunda process with CFO → assignee → CFO approval loop; per-person assignment; approved corrections written to Neon **and** back to Databricks |
| 6. Refresh | No: file-arrival trigger only | Daily schedule; "Refresh Now" button starting the job via the Jobs API, with progress status |

| ID | Task | Size | Needs confirming | Status |
|---|---|---|---|---|
| FLOW-1a | `source_system`, `source_country`, `ingest_batch_id`, `source_file` on every record from Notebook 1 through Neon (same as SRC-1; prerequisite for per-source reconciliation) - `specs/source-tagging.md` | M | Sources per country; region → country map | in progress: code + tests done 2026-09-24; migration 007 not yet on Neon, notebooks not yet run on the cluster |
| FLOW-1b | Completeness check: every expected source delivered this run, else flagged (not silently missing from totals) | S | Expected sources and cut-off times | todo |
| FLOW-1c | Connector + field/code mapping per new source system (file, API or database) | L per source | Each country's systems and delivery method; code lists (SRC-4) | blocked (bank) |
| FLOW-3 | Pipeline reconciliation: row counts + amount totals per source / data type / run at received, loaded and clean (Notebooks 1-2); one `reconciliation_items` row per gap, drill-down to the rejected records in `data_quality_exceptions`; shown on the Reconciliation tab - `specs/pipeline-reconciliation.md` | L | Which amounts to total (transactions, balances, loans; per currency) | in progress: code + tests done 2026-09-24; migration 008 not yet on Neon, notebook not yet run on the cluster, screen not yet checked in a browser |
| FLOW-5 | CFO workflow: new Camunda process - item → CFO → handle or reassign → assignee updates values + comments → submit → CFO approves or returns (loop); per-person assignment tracked in the app (proper Camunda identity, e.g. Keycloak, later); on approval, write to Neon immediately and to `review_outcomes` so Databricks applies it on the next run (not overwritten nightly) | L | Every item to the CFO, or only above an amount? Named people or teams? | in progress: 5a (workflow) code + tests done 2026-09-24 - `specs/cfo-reconciliation-workflow.md`; not yet deployed to Camunda or Neon (migration 009); 5b (Databricks applying approved corrections) not built |
| FLOW-6 | Refresh: daily schedule in `databricks.yml`; "Refresh Now" button (CFO/admin only) starting the job via the Jobs API, status shown ("started 10:42 → updated 10:51"), no overlapping runs. Not instant: a run takes minutes and costs compute | S-M | Is "a few minutes, with progress" acceptable? | todo |
| FLOW-4 | CFO dashboard: country breakdown (each country + bank-wide total) and one reporting currency for global totals | M | Reporting currency (₹, USD, ...) | todo |

**Recommendation on FLOW-5:** if every item goes to the CFO first, the CFO becomes a bottleneck.
Suggest: the CFO sees everything, large items go to the CFO first, smaller ones go straight to the
source's country finance team, and the CFO gives final approval above an amount limit.

**Questions for Ankit Sir:**
1. Reconciliation: only raw-vs-clean totals per source, or also comparison against each country's core/ERP system?
2. Which amounts to compare: transaction totals, balances, loan totals, per currency?
3. Does every item go to the CFO first, or only above an amount?
4. Assign to named people (needs logins linked to Camunda) or to teams?
5. Reporting currency for the global view?
6. Is "Refresh Now" taking a few minutes, with a progress indicator, acceptable?
7. Which systems does each of the 10 countries use (one or several per country), and how do they deliver data (file, API, database)?

## Rules for every task (from `CLAUDE.md`)

- [ ] Spec in `specs/` first, with a hand-traced acceptance/traceability table against the sample
      data; anything not run on a live cluster or in a browser is marked unverified.
- [ ] Placeholder values carry a UI footnote and are confirmed with the source-of-truth doc owner.
- [ ] New columns/tables → a new file in `db/migrations/`, applied to Neon with `db/apply_migration.py`.
- [ ] Notebook outputs in Delta, at the right medallion layer, with inline comments on each step;
      notebooks edited in Databricks, not locally at the same time.
- [ ] `flagged_transactions` / `reconciliation_exceptions` keep reviewer-set status on rerun;
      `poll_worker.py` stays idempotent (never starts the same process twice).
- [ ] Screens read precomputed summary tables (~2 s load target), never raw transactions on page load.
- [ ] BPMN/form changes redeployed with `camunda/bridge/deploy.py`; the Tasks screen keeps using Tasklist.
- [ ] `audit_log` stays insert-only; bulk actions write one row per record.
- [ ] pytest / vitest for backend and frontend changes; backlog status updated.

---

## 1. Automated reconciliation

*This point is **source reconciliation** (our copy vs the bank's core system). The target flow's
**pipeline reconciliation** (received vs clean, per source) is FLOW-3 above; both share the grouping,
task and Reconciliation-tab design below, pending confirmation that both are wanted.*

> Reconciliation can't be done one by one manually. Filters needed; tasks created automatically.

**Today:** Reconciliation screen has type tabs + a status filter; each break is resolved alone in a
popup (Accept / Correct / Dismiss). No tasks are created - `backend/app/routers/reconciliation.py`
deliberately keeps it separate from Camunda. $1 numeric tolerance exists
(`notebooks/multi_source_reconciliation.py`, `NUMERIC_TOLERANCE_USD`).

**Design (agreed for discussion 2026-09-24): a 3-step funnel.**
1. **Clear harmless breaks automatically:** within tolerance, formatting-only, and timing once a
   transaction feed exists. Every automatic decision is logged with the rule that made it.
2. **Group by cause, across accounts:** same run + source system + break type + field (+ same
   difference amount where useful) → one group = one task. Example: 412 accounts all +$15 from a
   late fee batch = 1 task, not 412.
3. **One decision per group:** Accept all / Accept all except selected (carve-outs become their
   own task) / Correct / Dismiss, with a mandatory reason; still one `audit_log` row per break.

Safety: important breaks (over an amount, key fields, missing accounts) are never bulk-cleared -
always their own task; large bulk decisions can require a second approver.

Example night: 600 breaks → 180 auto-cleared → **3 tasks** instead of 600.

**Where people work:**
- **Tasks screen** = the to-do list. Reconciliation decisions are made **only** in the task, so
  there is one route for decisions and one audit story.
- **Reconciliation tab** = the big picture, read-only: last run's summary, groups (with "Open
  task"), all breaks with filters (existing type tabs kept), ageing, recurring breaks, export, and
  run sign-off if required. The per-break resolve popup is replaced by a link to the task (admin
  override only if the bank asks for it).

**Task types in Camunda:** transaction alerts, data quality and breaches keep sharing
`transaction-review` (one team reviews → Approve / Reject / Correct). Reconciliation gets its own
`reconciliation-review` process, because bulk decisions, carve-outs and a second approval would
complicate the shared one. All types appear in the same Tasks screen, labelled by type.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| REC-1 | Automatic clearing: rules step after the comparison (tolerance, formatting-only; timing once REC-6 exists); rules + limits in a settings table; `resolved_by` = system + `rule` columns; "auto-cleared" filter on screen | M | Tolerances, which harmless causes to accept | todo |
| REC-2 | Group by cause across accounts: `reconciliation_groups` table + group id on each break; group view (summary, full list, filters, export) with Accept all / all-except-selected / Correct / Dismiss, reason required; carve-outs split out; one audit row per break | L | - | todo |
| REC-3 | Safety rules: important breaks (amount, key fields, missing accounts) never grouped for bulk, bulk accept blocked in the backend too; optional second approval above a total | M | Amount limits, key fields, second-approval rule | todo |
| REC-4 | Tasks: `reconciliation-review` Camunda process; bridge starts one task per group (idempotent, reusing TSK-1's case tracking); outcome worker writes the decision to every break in the group; due dates via TSK-3 | M | Owning team (placeholder: Operations), deadlines | todo |
| REC-5 | Ageing and recurring breaks: first/last seen + times seen; a rerun reopens a previously accepted break as "Recurring" (new task, never silently re-accepted); age buckets on screen | S-M | Escalation age | todo |
| REC-6 | Transaction-level matching (1:1, then 1:many): transaction feed from core banking, matching notebook (exact → near → one-to-many), matched-pairs table, side-by-side matching screen; runs in Databricks, screens read results only | L | **Transaction export + matching fields** | blocked (bank) |
| REC-7 | Run sign-off: `reconciliation_runs` table; preparer submits (no open important breaks, or a written explanation), reviewer signs off or returns; signed-off run locked; both logged | M | Whether required; who prepares / signs | todo |
| REC-8 | Reconciliation tab as the overview: run summary, groups list with "Open task", all-breaks explorer with the new filters, ageing and recurring views, export; resolve popup replaced by the task link | M | Admin override wanted? | todo |

Suggested order inside this point: REC-1 → REC-2 → REC-3 → REC-4 → REC-8 → REC-5 → REC-7; REC-6 once the bank provides a transaction feed.

**Done when:** a night of hundreds of breaks becomes a handful of tasks decided in minutes; nothing important is cleared in bulk; every automatic and bulk decision is in the audit trail per break.

**Plain-language summary (for stakeholders):** instead of checking hundreds of differences one by
one every night, the system clears the harmless ones automatically, groups the rest by cause into a
few tasks, and lets a person approve each group in one go - with big or risky items always checked
individually and everything recorded for audit.

---

## 2. Source tracking & flow

> Record the source against each transaction; show a clear happy flow from Source X onwards.

**Today:** `transactions` has no source column (id, account, date, amount, currency, type, channel
only). `CLAUDE.md` already lists `source_system` + `transaction_code_mapping` as a blocked gap.
Five `multi_source_*` ingestion notebooks exist; only Neon is verified live.
`reconciliation_exceptions` does carry `source_system`.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| SRC-1 | Add `source_system` + `ingest_batch_id` (file/run reference) to every entity, from Notebook 1 through `load_to_postgres.py` into Neon | M | - | in progress: same work as FLOW-1a |
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
| FRD-1 | Reclassify flags into **THRESHOLD** (reporting) / **SUSPICIOUS** (AML or fraud pattern) / **OPERATIONAL**; update routing + UI labels | S | - | in progress: code + tests done 2026-09-24; migration 006 not yet applied to Neon, Notebook 5 not yet run on the cluster |
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

**Today:** nothing. Reports has fixed views with PDF/Excel export and an insert-only `audit_log`.

**Decision (2026-09-24): rule-based, no AI.** The chatbot only has to fill approved reports, so
fixed rules parse the question; nothing leaves the bank and no external-AI approval is needed. A
controlled AI parser can replace CHT-2 later without touching CHT-1/3/4 (the earlier AI design's
number-checking guardrail is dropped: there is no model text to check). Proposal - confirm with the
bank and the source-of-truth doc owner.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| CHT-1 | Catalogue of approved, read-only queries (KPIs, report lines, portfolio/branch aggregates) with allowed filters; reads precomputed summary tables only | M | Which reports it must answer | todo |
| CHT-2 | Rule-based parser: synonym list ("NPL" = "bad loans"), branch/product/customer names from the database, date and currency phrases, fuzzy matching for typos; read-only DB role | M | - | todo |
| CHT-3 | Answer panel on Reports: table, "filters used", Excel export (reuse existing export); unclear or missing filter → follow-up question with buttons, never a guess | M | - | todo |
| CHT-4 | Every question, matched query, filters and row count written to `audit_log` | S | - | todo |
| CHT-5 | Test set of sample questions, each with its expected query + filters | S | - | todo |

**Done when:** a typed question returns an exportable table whose every number came from the database, with the filters shown and the request audited; anything it can't parse gets a follow-up question.

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
4. **7** - rule-based, so nothing blocks it; only the report list is needed from the bank.
5. **4 → 2 → 3** - each needs a bank input (official FX source, source-system code lists,
   registration IDs) to be real.

## Waiting on the bank (collected)

- Target flow: the 7 questions for Ankit Sir (FLOW section above)
- Official limits per level, consecutive-days rule and deadlines (BRC-1/2/3)
- AML typologies and reporting thresholds (FRD-3); device/login/beneficiary data (FRD-4)
- SLAs per team and task-creation sign-off (TSK-3/4)
- Reconciliation tolerances, harmless causes, key fields, second-approval rule, owning team and deadlines, escalation age, run sign-off requirement (REC-1/3/4/5/7); core-banking transaction export (REC-6)
- Official FX source per currency; which LBP rate per report (FX-2/3)
- Source-system list and transaction-code lists (SRC-4)
- A reliable company identifier (DUP-2)
- List of reports and filters the chatbot must cover (CHT-1)
