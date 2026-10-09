# Client Feedback Backlog (CFO/COO review, 2026-09-23)

Eight points raised by the bank after the demo walkthrough, each broken into buildable tasks.
"Today" describes the app as of 2026-09-23 (checked against the code, not assumed).

**Legend**
- Size: **S** ≈ under a day · **M** ≈ 1-3 days · **L** ≈ a week or more
- **Bank input**: the task can be built with a clearly-labelled placeholder, but only becomes
  *real* once the bank supplies what's named. Placeholders get a UI footnote, same as the
  existing NIM / cost-to-income / ROE assumptions.
- Status: `todo` / `in progress` / `done` / `blocked (bank)`

**Live check (2026-09-28):** statuses below were re-checked against Neon, Camunda and the running API
(not a browser - the screens themselves are still unchecked). Migrations 007-016 are all on Neon; the
pipeline has run live (latest run 2026-09-28, 4 ingest batches); all three Camunda processes are
deployed and 139 tasks are open across the five teams; every read endpoint answers for all four roles.
"Ran live" below means the automatic part produced real rows in Neon; the human decision steps are
listed separately where they haven't been exercised. The same check found and fixed every screen call
taking 2.5 s+ (the connection pool reconnected to Neon per query - commit `44024fa`); typical calls
now take ~0.3 s.

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
| FLOW-1a | `source_system`, `source_country`, `ingest_batch_id`, `source_file` on every record from Notebook 1 through Neon (same as SRC-1; prerequisite for per-source reconciliation) - `specs/source-tagging.md` | M | Sources per country; region → country map | done: ran live - every customer and all 1,905 transactions carry `source_system` / `source_country` (checked 2026-09-28) |
| FLOW-1b | Completeness check: every expected source delivered this run, else flagged (not silently missing from totals) | S | Expected sources and cut-off times | done: ran live - migration 011 on Neon; the run flagged `fx_rates` as "No rows delivered" (`specs/pipeline-reconciliation.md` section 9); expected sources still to confirm with the bank |
| FLOW-1c | Connector + field/code mapping per new source system (file, API or database) | L per source | Each country's systems and delivery method; code lists (SRC-4) | blocked (bank) - demo uses CSV sources only until further notice |
| FLOW-3 | Pipeline reconciliation: row counts + amount totals per source / data type / run at received, loaded and clean (Notebooks 1-2); one `reconciliation_items` row per gap, drill-down to the rejected records in `data_quality_exceptions`; shown on the Reconciliation tab - `specs/pipeline-reconciliation.md` | L | Which amounts to total (transactions, balances, loans; per currency) | done: ran live - 72 per-source rows over 4 runs, 62 matched and 10 with a gap (checked 2026-09-28); not yet checked in a browser |
| FLOW-5 | CFO workflow: new Camunda process - item → CFO → handle or reassign → assignee updates values + comments → submit → CFO approves or returns (loop); per-person assignment tracked in the app (proper Camunda identity, e.g. Keycloak, later); on approval, write to Neon immediately and to `review_outcomes` so Databricks applies it on the next run (not overwritten nightly) | L | Every item to the CFO, or only above an amount? Named people or teams? | built (code + tests done 2026-09-24): 5a workflow + 5b Databricks applying approved corrections - `specs/cfo-reconciliation-workflow.md`. Partly live: migration 009 on Neon, `reconciliation-review` deployed, 9 gaps waiting with the CFO; item 32 was reassigned and submitted back on 2026-09-24 but the CFO's final approval - and so 5b (Databricks applying the correction) - has never run |
| FLOW-6 | Refresh: daily schedule in `databricks.yml`; "Refresh Now" button (CFO/admin only) starting the job via the Jobs API, status shown ("started 10:42 → updated 10:51"), no overlapping runs. Not instant: a run takes minutes and costs compute | S-M | Is "a few minutes, with progress" acceptable? | built (code + tests done 2026-09-24) - `specs/refresh-now.md`; needs DATABRICKS_HOST/TOKEN in backend/.env (still unset on 2026-09-28: `/refresh/status` returns 503); daily schedule vs file-arrival trigger to confirm; not run live |
| FLOW-4 | CFO dashboard: country breakdown (each country + bank-wide total) and one reporting currency for global totals | M | Reporting currency (₹, USD, ...) | built (code + tests done 2026-09-24) - `specs/cfo-country-view.md`, USD. Ran live: 3 countries per day in `country_performance_summary` (24, 25 and 28 Sep), `/kpi-summary/countries` answers; not yet checked in a browser |

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
| REC-1 | Automatic clearing: rules step after the comparison (tolerance, formatting-only; timing once REC-6 exists); rules + limits in a settings table; `resolved_by` = system + `rule` columns; "auto-cleared" filter on screen | M | Tolerances, which harmless causes to accept | done: ran live - a break auto-accepted with its rule recorded - `specs/reconciliation-groups.md` |
| REC-2 | Group by cause across accounts: `reconciliation_groups` table + group id on each break; group view (summary, full list, filters, export) with Accept all / all-except-selected / Correct / Dismiss, reason required; carve-outs split out; one audit row per break | L | - | done: ran live - 13 groups; two decided through their tasks on 2026-09-24 (group 7 corrected, group 10 accepted), each with one audit row per break; carve-outs not yet exercised |
| REC-3 | Safety rules: important breaks (amount, key fields, missing accounts) never grouped for bulk, bulk accept blocked in the backend too; optional second approval above a total | M | Amount limits, key fields, second-approval rule | built 2026-09-24 (code + tests); runs live as part of grouping, but the blocked bulk accept and the second approval haven't been tried live |
| REC-4 | Tasks: `reconciliation-review` Camunda process; bridge starts one task per group (idempotent, reusing TSK-1's case tracking); outcome worker writes the decision to every break in the group; due dates via TSK-3 | M | Owning team (placeholder: Operations), deadlines | done: ran live - `reconciliation-group-review` deployed, one task per group (11 open), the bridge rerun started none twice (2026-09-28) |
| REC-5 | Ageing and recurring breaks: first/last seen + times seen; a rerun reopens a previously accepted break as "Recurring" (new task, never silently re-accepted); age buckets on screen | S-M | Escalation age | done: ran live - 2 breaks marked Recurring (seen twice) |
| REC-6 | Transaction-level matching (1:1, then 1:many): transaction feed from core banking, matching notebook (exact → near → one-to-many), matched-pairs table, side-by-side matching screen; runs in Databricks, screens read results only | L | **Transaction export + matching fields** | blocked (bank) |
| REC-7 | Run sign-off: `reconciliation_runs` table; preparer submits (no open important breaks, or a written explanation), reviewer signs off or returns; signed-off run locked; both logged | M | Whether required; who prepares / signs | built 2026-09-24 (code + tests); half live - the 2026-09-24 run was submitted, the sign-off / return step hasn't been done |
| REC-8 | Reconciliation tab as the overview: run summary, groups list with "Open task", all-breaks explorer with the new filters, ageing and recurring views, export; resolve popup replaced by the task link | M | Admin override wanted? | built 2026-09-24 (code + tests); its endpoints answer against live data (2026-09-28), not yet checked in a browser |
| REC-9 | Fix-at-source status per approved correction: each run, Notebook 1 records for every `APPROVED` correction in `reconciliation_corrections` one of *still wrong at source* (old value sent, correction applied), *fixed at source* (source now sends the approved value), *changed to something else* (needs another look) or *no longer sent* - today `applied_corrections` records only the first. A "Fix at source" list per source system on the Reconciliation tab (status, days applied, date fixed) and a monthly figure ("38 approved, 31 fixed at source, average 4 days") | M | - | todo (added 2026-10-01) |
| REC-10 | Tell the source owner: when the CFO approves a correction, a task goes to the owner of that source system ("Core banking: change C-1001 country from KSA to Saudi Arabia"); it closes by itself when a delivery arrives with the approved value (REC-9's *fixed at source*), with an audit row; *changed to something else* reopens it for review | M | **Owner of each source system, and how they want to be told (task, email, file)** | todo (added 2026-10-01) |
| REC-11 | Corrections file: export open corrections per source system (record, field, current value, approved value, approved by / on) for the source team to work through or load | S | Format the source teams can use | todo (added 2026-10-01) |

Suggested order inside this point: REC-1 → REC-2 → REC-3 → REC-4 → REC-8 → REC-5 → REC-7; REC-6 once the bank provides a transaction feed.

**Fixing at source (REC-9..11):** an approved correction never changes the source system - the platform
keeps it in `reconciliation_corrections` and Notebook 1 reapplies it each run while the source still sends
the old value (the source wins once it sends anything else). So the platform's figures stay right, but
the core banking system or CRM stays wrong until its own team fixes it, and today nobody is told. Order:
REC-9 (needs no bank input) → REC-10 once the source owners are known → REC-11 if a source team asks for
a file. Writing fixes straight back into a source system is not proposed: banks rarely let an outside
platform write into core banking, and it would need the bank's explicit approval (a CRM could take it
through its API if asked).

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
| SRC-1 | Add `source_system` + `ingest_batch_id` (file/run reference) to every entity, from Notebook 1 through `load_to_postgres.py` into Neon | M | - | done: same work as FLOW-1a, live since the 2026-09-24 run |
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
| DUP-1 | Name normalisation (drop Ltd / SAL / Pvt / Inc, case, punctuation) + known-abbreviation list | S | Abbreviation list (optional) | done: ran live (feeds DUP-2's 30 candidates) - `specs/entity-matching.md` |
| DUP-2 | Candidate matching: fuzzy name + shared registration/tax ID, phone, address → `entity_match_candidates` | M | **A reliable ID, e.g. commercial registration no.** | done: ran live - 30 candidate pairs in `entity_match_candidates`; name-based until a registration number exists |
| DUP-3 | Review queue: each candidate pair becomes a task; a human confirms or rejects (never auto-merge) | M | - | built 2026-09-24 (code + tests); 30 review tasks started live, none confirmed or rejected yet |
| DUP-4 | `master_entity_id` on customers; exposure/concentration aggregates group by it; originals untouched | M | - | built 2026-09-24 (code + tests) - top exposures per group (Notebook 6); nothing to roll up live yet, since no pair has been confirmed (`customer_entity` is empty) |

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
| FRD-1 | Reclassify flags into **THRESHOLD** (reporting) / **SUSPICIOUS** (AML or fraud pattern) / **OPERATIONAL**; update routing + UI labels | S | - | done: live since the 2026-09-24 run (94 Suspicious / 2 Threshold / 2 Operational) |
| FRD-2 | New suspicious patterns possible with current data: dormant account reactivated; pass-through (in and out same day); activity too big for segment; many round amounts; splitting across a customer's accounts | M | - | done: ran live - all five patterns flagged real rows (dormant 1, pass-through 2, round amounts 3, split 2, unusual for segment 3) - `specs/notebook-05-fraud-business-rules.md` 3a |
| FRD-3 | Thresholds and typologies from config, not hard-coded constants | S | **Bank's AML typologies + reporting thresholds** | done: live - `app_settings['fraud.rules']`, migration 013; values are placeholders until the bank supplies its own |
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
| TSK-1 | Case grouping: one task per account + day (or per pattern) listing all related flags | M | - | done: ran live - 81 cases for 2026-09-15 to 09-28, one task each - `specs/task-cases.md` |
| TSK-2 | Severity score per case; only above a threshold becomes a task, the rest go to a daily digest | M | Severity rules | done: ran live - 68 High / 13 Medium; no Low cases so far, so the daily digest is still empty live |
| TSK-3 | Due date by severity/team; overdue badge on Tasks and Audit & Oversight | S | **SLA per team** | built 2026-09-24 (code + tests) - due dates set on live cases; the overdue badge not yet checked in a browser |
| TSK-4 | Written task-creation policy (what, who, how fast) shown in the UI | S | **Sign-off** | built 2026-09-24 (code + tests) - policy shown on Tasks from settings (`/workflow/policy` answers live); bank sign-off pending |

**Done when:** the queue holds cases, not raw flags, each with a priority and a deadline.

---

## 7. Conversational reporting

> A chat box in Reports: "Give me the report for X, Y, Z" → a table.

**Today (2026-09-23):** nothing. Reports has fixed views with PDF/Excel export and an insert-only `audit_log`.

**Decision (2026-09-24): rule-based, no AI.** The chatbot only has to fill approved reports, so
fixed rules parse the question; nothing leaves the bank and no external-AI approval is needed. A
controlled AI parser can replace CHT-2 later without touching CHT-1/3/4 (the earlier AI design's
number-checking guardrail is dropped: there is no model text to check). Proposal - confirm with the
bank and the source-of-truth doc owner.

**Superseded 2026-09-28 (CHT-2 only):** at the manager's request, CHT-2's rule-based parser was replaced
by a **self-hosted language model** (Ollama on the laptop now, vLLM inside the bank later) that only
*picks* one of 11 approved queries; plain code reads dates, counts and names from the text, and the
model never writes SQL or produces a number. Built as the "Ask a question" tab - `specs/ask-a-question.md`.
The bank still needs to confirm this replaces the 2026-09-24 decision (spec section on open items).

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| CHT-1 | Catalogue of approved, read-only queries (KPIs, report lines, portfolio/branch aggregates) with allowed filters; reads precomputed summary tables only | M | Which reports it must answer | built 2026-09-28 - 11 approved queries; the bank's report list still needed |
| CHT-2 | Rule-based parser: synonym list ("NPL" = "bad loans"), branch/product/customer names from the database, date and currency phrases, fuzzy matching for typos; read-only DB role | M | - | built 2026-09-28 **as a self-hosted model + word lists** (see note above); ran live 2026-09-28 against qwen2.5:3b via the API (answer, clarify and "can't exclude" all correct) |
| CHT-3 | Answer panel on Reports: table, "filters used", Excel export (reuse existing export); unclear or missing filter → follow-up question with buttons, never a guess | M | - | built 2026-09-28 - on its own "Ask a question" tab rather than inside Reports; used from the admin login on 2026-09-28 (audited), not yet walked through end to end |
| CHT-4 | Every question, matched query, filters and row count written to `audit_log` | S | - | done: live - each question is an `ASK_QUESTION` row with query, filters, status, row count and time |
| CHT-5 | Test set of sample questions, each with its expected query + filters | S | - | done - golden 54 (0 wrong tables), hard 29, held-out 30 (1 wrong, since fixed, so no longer blind); `scripts/eval_ask.py` |

**Done when:** a typed question returns an exportable table whose every number came from the database, with the filters shown and the request audited; anything it can't parse gets a follow-up question.

---

## 8. Breach marking: when is something a breach?

**Today:** `limits` (KPI, threshold, direction) + `breach_check.py` compares the latest KPI; a new
breach creates a Compliance task. Two **placeholder** limits set 2026-09-23: capital ratio below
12.5%, NPL above 5%. Dashboard tiles hold a **separate copy** of thresholds in
`frontend/src/kpi/kpiConfig.js`, which can drift from `limits`.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| BRC-1 | Three levels per limit: regulatory minimum / internal risk appetite / early warning (early warning = notification, not a task) | M | **Official values per level** | done: ran live - 7 limits with levels (all placeholders); 2026-09-24 breaches: CAR early warning (notification only), NPL / ROE / dollarization at appetite level (tasks) - `specs/breach-levels.md` |
| BRC-2 | Consecutive-days rule per limit (e.g. breached 3 days running) in `breach_check.py` | S | **Rule per limit** | built 2026-09-24 (code + tests); live, but every limit is set to 1 day, so the multi-day rule hasn't actually been exercised |
| BRC-3 | Deadline from `resolution_days`; due date + overdue shown on breach tasks and Audit & Oversight | S | Deadlines | done: ran live - open breaches due 2026-10-24 from `resolution_days` |
| BRC-4 | Tiles read thresholds from `limits` via the API - one source of truth, remove the copy in `kpiConfig.js` | M | - | built 2026-09-24 (code + tests) - tiles read /kpi-summary/limits, which answers live; tiles not yet checked in a browser |

**Done when:** the bank's own limits drive both the tiles and the breach tasks, at the right level, with deadlines.

---

## 9. Data ingestion screen and AI assistant: demo content to make real (manager review, 2026-09-29)

**Today (built 2026-09-29, not yet checked in a browser):** both tabs now follow the client demo deck
(`project-docs/client-demo/AppBay-Client-Demo.pdf`, slides 3 and 12). The **Data ingestion** tab
(`/ingestion`, first in the menu, `specs/screen-data-ingestion.md`) shows the **real** latest pipeline run
from `pipeline_reconciliation`: files, records received / kept / held back, sources that delivered
nothing, and one "Recent ingestions" row per source, country and data type. Everything else on it is
**demo content** from `DEMO` in `backend/app/routers/ingestion.py`, labelled "Demo data" on screen: the
six source connectors and their status, "Sources connected 5 / 6", the scheduled pulls, and file
upload, which checks type and size in the browser but sends nothing. With no pipeline run in the
database, the stat cards and "Recent ingestions" fall back to demo rows too, also labelled. The **AI
assistant** tab (`/ask`, last in the menu) lists six areas under "Querying": four it answers from, and
Reconciliation and Regulatory reports shown unticked because it can't answer questions about them yet.

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| ING-1 | Connector registry: a `source_connectors` table (type, target, country, credentials reference - never the secret itself - status, last check) replacing `DEMO["connectors"]`; "Connect" opens a real setup form; status from a periodic connection check | L | Each source's system, delivery method and credentials owner (same as FLOW-1c) | part 1 built 2026-09-29: `source_connectors` (migration 018, on Neon), Connect / Test / Configure / Disconnect / Sync forms for Salesforce, PostgreSQL, REST API, AWS S3, Snowflake; credentials go to the Databricks secret scope, never Postgres. Salesforce done end to end 2026-09-29 (client-credentials External Client App → `salesforce_ingest` task → `bronze_salesforce_accounts`, run recorded in `ingestion_runs`). Still to do: notebooks wired the same way for PostgreSQL, REST API, AWS S3 and Snowflake, and a live sign-in check in Test connection |
| ING-2 | Schedules from the real jobs: next run and cadence per connector from the Databricks Jobs API (`databricks.yml` today has one file-arrival trigger, shown as "Schedule: on file arrival"), replacing `DEMO["schedules"]` | M | Pull times per source | todo - demo only |
| ING-3 | File upload for real: `POST /ingestion/uploads` streams the file to the landing volume (`/Volumes/.../resources`), which starts the pipeline by its file-arrival trigger; virus/size/type checks server-side; one audit row per upload; admin/CFO only. XLSX/JSON/XML need readers in Notebook 1; PDF needs a table-extraction step first (`PREREQUISITES.md` question 8) | L | Which sources may be uploaded by hand, and who may upload | done 2026-09-30 for the eight core banking CSVs (`POST /ingestion/upload`, Databricks Files API, CFO/admin, audited; `specs/screen-data-ingestion.md` 3b); other formats and virus scanning still todo |
| ING-4 | Failed loads from the source side: connector errors (e.g. "authentication expired") recorded per attempt in an `ingestion_runs` table, so a source that never reached Databricks still shows as failed (today only "No rows delivered" from the completeness check, FLOW-1b, counts) | M | - | todo |
| ING-5 | "Recent ingestions" across several runs, not just the latest, with a filter by source and date and a drill-down to the rejected records (reuse the Reconciliation tab's `/reconciliation/pipeline/{id}/records`) | S | - | todo - latest run only |
| ING-6 | Remove the demo fallback (`_demo_recent`) once the pipeline always has a run in every environment, so an empty database says "No loads yet" instead of showing demo rows | S | - | todo |
| ING-7 | CRM reconciliation: Salesforce Accounts vs our business customers (name, country) on the Reconciliation tab, same groups / tasks / sign-off as core banking - `specs/multi-source-reconciliation.md` 3a | M | Which CRM fields must agree with core banking | done 2026-09-29: ran live, 5 planted differences found exactly, 4 groups; tasks start when the Camunda worker next runs |
| AST-1 | Assistant answers about reconciliation: an approved query over `reconciliation_groups` / `reconciliation_items` (open groups by cause, largest breaks, second approvals), added to the catalogue, prompt examples and the golden question set (`scripts/eval_ask.py`); then tick "Reconciliation" | M | - | todo |
| AST-2 | Assistant answers about regulatory reports: report calendar and line values from `report_instances` / `report_line_items`, with the drill-to-source link to the report line; then tick "Regulatory reports" | M | The bank's report list (same as CHT-1) | todo |
| AST-3 | "View records" to the exact rows: today it opens the matching screen (e.g. Portfolio for loan questions); pass the answer's filters so that screen opens already filtered | S | - | todo |

**Done when:** every block on the Data ingestion tab reads from a real source (no "Demo data" labels
left) and the assistant ticks every area listed under "Querying".

---

## 10. Encryption and data protection (planned 2026-10-08)

**Today:** browser → API is plain HTTP; Camunda's internal traffic is unencrypted (`create_insecure_channel`,
Elasticsearch security off, `demo/demo` login in `frontend/src/workflow/tasklistApi.js`); stored data uses
provider-held keys; customer names are shown unmasked to every role. See
`project-docs/REGULATORY-COMPLIANCE-GAPS.md` items 7, 15-18.

**Plan:** a 5-day phase 1 (Fri 9 Oct → Thu 15 Oct 2026, one developer with Claude Code, weekends off) that
**does not change stored data**: masking happens only in API responses and exports, so the pipeline,
reconciliation (which compares names, `multi_source_reconciliation.py`) and duplicate detection (which
scores name similarity, `camunda/bridge/duplicates_db.py`) keep working unchanged. Full tokenisation and
Camunda security follow in phase 2 (~12 days). Built to industry standards (NIST, PCI DSS, ISO 27001) until
the bank's own cryptography policy is available.

**Phase 1 (5 days, with regression testing):**

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| ENC-0 | Azure trial check: expiry date and credit left ($200 / 30-day free account); upgrade to pay-as-you-go if it ends before 15 Oct | S | - | todo (Fri 9 Oct) |
| ENC-1 | Key Vault: login-signing key and database connection secrets; Databricks secret scope backed by Key Vault | S | - | todo (Fri 9 Oct) |
| ENC-2 | Regression baseline before any change: pytest (244) + vitest (218) results; snapshot of KPIs, data-quality exceptions, flagged transactions, reconciliation counts and Neon row counts / totals | S | - | todo (Fri 9 Oct) |
| ENC-3 | Databricks TLS: `sslmode=verify-full` in `load_to_postgres.py`, `core_banking_ingest` and the Neon ingestion notebook (Java's built-in certificate store on serverless); confirm the loan API call uses HTTPS with certificate checks; pipeline run compared with the baseline (every number must match) | S | - | todo (Mon 12 Oct) |
| ENC-4 | Backend: `verify-full` to Neon, signing key from Key Vault, scripts updated; masking module + which roles see real names in `roles.py`; names masked in every API response; pytest for all 7 roles | M | **Which roles see real names** (suggested: Reconciliation Analyst and Compliance Officer) | todo (Wed 14 Oct) |
| ENC-5 | Masked PDF / Excel exports; logged Reveal endpoint (one `audit_log` row per reveal) with the button on the reconciliation and duplicate-review panels; HTTPS on the app (mkcert); vitest; Camunda routes, outcomes and poll-worker idempotency re-checked | M | - | todo (Wed 14 Oct) |
| ENC-6 | Final regression: live pipeline run and baseline comparison (zero differences expected), browser check as each of the 7 roles, no real names in API responses or exports for masked roles, TLS scan (testssl.sh), sign-off | S | - | todo (checkpoint Fri 16 Oct, final Mon 2 Nov) |

**Phase 2 (~12 days):**

| ID | Task | Size | Bank input | Status |
|---|---|---|---|---|
| ENC-7 | Full tokenisation of stored names (HMAC tokens at Bronze, encrypted `token_vault` in Databricks and Neon); name clean-up must match today's comparison (trim only) so reconciliation counts don't change; migrate the names already in `reconciliation_exceptions` and `entity_match_candidates` | L | Data classification (which fields are sensitive) | todo |
| ENC-8 | Duplicate detection on tokenised data: trusted, logged reveal for `duplicates_db.py` so name-similarity scoring keeps working | S | - | todo (needs ENC-7) |
| ENC-9 | Camunda security: local certificate authority, Elasticsearch security + TLS, Zeebe gateway TLS, Tasklist HTTPS, workers on `create_secure_channel`, Tasklist calls behind a FastAPI proxy (removes `demo/demo` from the browser) | L | - | todo |
| ENC-10 | Bank-controlled keys in Databricks (managed services, workspace storage, managed disks) and on the Unity Catalog storage account. Only after the subscription can't lapse: an expired trial would leave the data unreadable | M | Who holds the keys (our subscription for the POC; the bank's tenant for production) | todo |
| ENC-11 | Tamper-evident `audit_log`: each row hashes the previous one (serialised inserts), existing rows backfilled, IP recorded at all 12 insert sites, chain-check script | M | - | todo |
| ENC-12 | Login token in a secure cookie (HttpOnly, SameSite) with CSRF protection | S | - | todo |
| ENC-13 | Key rotation tested for real; rotation runbook, key-management procedure, evidence pack for auditors | M | - | todo |
| ENC-14 | Optional: tokenise customer / account / loan IDs (+3 days); move Neon to Azure PostgreSQL in UAE North with bank-controlled keys (+5 days, fixes key custody and data residency); Camunda Identity with OAuth (+4 days) | L | Hosting and residency decision | todo |

**Schedule (revised 2026-10-08): phases 1 and 2 together, ENC-14 excluded, 7 hours a day.** Both phases
need ~50-57 hours of hands-on time, so they can't fit in 5 days. The developer is off **Mon 19 - Mon 26 Oct**,
so the work is split into two blocks, and the first block ends in a stable, fully tested state: no
half-finished Camunda or key change is left running over the break. Realistic finish **Mon 2 Nov**
(best case Thu 29 Oct, worst case Wed 4 Nov).

| Day | Tasks | Stop rule |
|---|---|---|
| Fri 9 Oct | ENC-0 (**upgrade to pay-as-you-go before the break**: the trial ends by ~22 Oct), ENC-1 Key Vault (signing, master, token keys), ENC-2 baseline; encryption/tokenisation library + tests; backups: Neon branch, Camunda volumes | Not upgraded → ENC-10 is dropped, and app-critical keys need a local fallback |
| Mon 12 Oct | ENC-3 Databricks TLS; ENC-7 tokenisation in the notebooks **on a test schema**, compared with the baseline | Numbers or reconciliation counts differ → no Neon migration until fixed |
| Tue 13 Oct | ENC-7 Neon side (TLS, `token_vault`, migrate names incl. `reconciliation_exceptions` / `entity_match_candidates`); ENC-8 duplicate detection | Migration fails → restore the Neon branch |
| Wed 14 Oct | ENC-4 masking by role; ENC-5 masked exports, Reveal, HTTPS; pytest + vitest | - |
| Thu 15 Oct | ENC-11 audit hash chain; regression check | - |
| Fri 16 Oct | Buffer for fixes; ENC-6 full regression as a **checkpoint sign-off** (phase 1 + tokenisation + audit chain); budget alert set; pipeline trigger paused for the break | Anything unstable is rolled back before leaving |
| *Mon 19 - Mon 26 Oct* | *Off* | |
| Tue 27 Oct | Quick re-check against the baseline; ENC-9 Camunda security starts (certificates, Elasticsearch security + TLS) | - |
| Wed 28 Oct | ENC-9 continued: Zeebe TLS, Tasklist HTTPS, secure worker channels | - |
| Thu 29 Oct | ENC-9 finished: Tasklist proxy; routes, outcomes and poll-worker idempotency re-tested | Camunda not healthy by end of day → restore the volumes and the compose file, rethink before continuing |
| Fri 30 Oct | ENC-10 bank-controlled keys in Databricks; ENC-12 secure cookie + CSRF | - |
| Mon 2 Nov | ENC-13 one real key rotation + evidence pack; ENC-6 final regression and sign-off | Any regression difference → fix before sign-off |

**Done when:** every connection uses TLS 1.2+ with certificate checks, every key lives in Key Vault, real
customer names are only seen by roles allowed to see them (and every reveal is logged), and the
regression comparison shows no change to any number or reconciliation count.

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
- Owner of each source system and how they want to hear about fixes needed at source - task, email or file (REC-10/11)
- Official FX source per currency; which LBP rate per report (FX-2/3)
- Each source system's delivery method, credentials owner and pull times; who may upload files by hand (ING-1/2/3)
- Source-system list and transaction-code lists (SRC-4)
- A reliable company identifier (DUP-2)
- List of reports and filters the chatbot must cover (CHT-1)
- The bank's cryptography policy and data classification; which roles may see real customer names;
  who holds the encryption keys in production (ENC-4/7/10)
