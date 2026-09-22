# Spec: Camunda 8 Process Design — Transaction Review Workflow

**Status:** Verified live end-to-end (2026-09-22) — BPMN process and form deployed to a real
Zeebe/Tasklist (`camunda/bridge/deploy.py`), all three `flagCategory` routes confirmed via
`test_instance.py` + a real `/v1/tasks/search`, and all three outcomes (Approved/Rejected/Corrected,
including a Corrected value round-tripping into `review_outcomes`) completed through Tasklist's
REST API and picked up by `outcome_worker.py`. Not yet run: the Postgres-driven bridge worker
(`poll_worker.py`) against a real `data_quality_exceptions` row (acceptance criteria below), and
Screen 6's own UI end to end.
**New for:** the 3-week Camunda-based POC extension — see `3-WEEK-POC-PLAN.md`
**Decision context:** Camunda 8, **self-hosted**, confirmed by the user over the source doc's
original "don't use a workflow engine for the POC" guidance — that guidance is explicitly
overridden for this extension. See `CLAUDE.md` for the current state of that decision.
**Depends on:** `specs/notebook-02-bank-data-quality.md` (`data_quality_exceptions`),
`specs/notebook-05-fraud-business-rules.md` (`flagged_transactions`), PostgreSQL schema (Phase 1)

---

## 1. Objective

Define the BPMN process that turns a flagged record (data-quality exception or fraud/fault
transaction) into a routed, assigned, trackable human task — replacing the simpler "status
column + API endpoints" design the source doc originally recommended for a plain POC.

## 2. Infrastructure (self-hosted Camunda 8)

Minimum stack, via Docker Compose (the "Camunda 8 Run" self-managed bundle, or an equivalent
compose file):

- **Zeebe** — the process engine/broker that executes the BPMN process
- **Elasticsearch** — required dependency for Operate (process/incident monitoring)
- **Operate** — operational visibility into running process instances (useful for debugging
  during the build, not necessarily demoed)
- **Tasklist** — human task UI and REST API; the React frontend calls Tasklist's REST API rather
  than reimplementing task management from scratch

**Not included for the POC:** Camunda Identity/Keycloak-based auth (use Tasklist's basic
auth/seeded users, consistent with the application layer's "four seeded demo users" decision in
`CLAUDE.md`), Optimize (analytics — redundant with the React Executive Summary screen), Connectors
runtime (the bridge job described in section 4 is a small custom worker instead, since the
connector catalog is overkill for one specific integration).

## 3. Process Definition: `transaction-review`

### Trigger

A process instance is created **per flagged record** (one per `data_quality_exceptions` row *or*
`flagged_transactions` row that requires human review — see section 5 for which ones do).

### Process variables (set at instance creation)

| Variable | Source | Purpose |
|---|---|---|
| `recordType` | `"data_quality"` or `"fraud"` | which source table/flow this came from |
| `sourceTable` | `data_quality_exceptions.source_table` or `"transactions"` | |
| `recordKey` | `data_quality_exceptions.record_key` or `flagged_transactions.transaction_id` | the join key back to Postgres |
| `flagLabel` | e.g. `MISSING_RISK_RATING`, `LARGE_AMOUNT` | |
| `flagType` | `"FRAUD"` or `"FAULT"` (data-quality records are always treated as `"FAULT"`) | input to `flagCategory` derivation below |
| `flagCategory` | derived: `"FRAUD"` / `"COMPLIANCE"` / `"OPERATIONS"` — see the flow section for the derivation rule | drives the gateway |
| `description` | human-readable description | shown in the task detail |

### Flow

```
[Start: Record Flagged]
        |
   (Exclusive Gateway: flagCategory?)
   /            |              \
 FRAUD      COMPLIANCE        FAULT
  |             |                |
[User Task:  [User Task:     [User Task:
 Fraud        Compliance      Operations
 Investigation] Review]        Review]
  |             |                |
   \            |               /
     (Gateway: outcome?)
     /      |       \
 Approved Rejected  Corrected
   |        |          |
    \       |         /
   [Service Task: Write outcome back to Postgres]
         |
      [End]
```

- **`flagCategory` derivation (resolves the 3-way routing gap with a documented assumption, per
  the decision to make all 6 screens fit the 3-week timeline rather than leave this blocked):**
  - `flagType = "FRAUD"` (from `flagged_transactions`) → **`flagCategory = "FRAUD"`** →
    `fraud-investigation` candidate group
  - `flagType = "FAULT"` **and** `sourceTable` in `{capital_positions, liquidity_daily, fx_rates}`
    → **`flagCategory = "COMPLIANCE"`** → `compliance` candidate group. Rationale: these three
    tables feed the KPIs regulators actually check (CAR from `capital_positions`, LCR from
    `liquidity_daily`); a data-quality issue there is a regulatory-reporting-integrity concern,
    not a routine data-entry fix.
  - `flagType = "FAULT"` and `sourceTable` in `{customers, accounts, loans, branches,
    transactions}` (i.e. `DUPLICATE_TRANSACTION` from Notebook 5, or any Notebook 2 structural
    check) → **`flagCategory = "OPERATIONS"`** → `operations` candidate group
  - **This is an assumption, not a specification the user provided** — the original process
    description names all three groups but never defines what makes something a "compliance
    issue." Confirm this table-based split with whoever owns the process requirements; it's a
    reasonable placeholder for demo purposes, not a verified business rule.
- **User task outcome** maps to the status vocabulary from the original process description:
  `Approved` / `Rejected` / `Corrected` (data-quality records) — `Corrected` implies the reviewer
  edited the underlying value, which needs a form field for the corrected value, not just a
  decision button.
- **Service task** at the end calls a small internal endpoint (or writes directly via a Zeebe job
  worker with a Postgres client) to update the record's status and, if corrected, its value —
  this is the write side of `specs/bidirectional-sync.md`.

## 4. Bridge Worker: Postgres → Zeebe

Something has to notice a new row in `data_quality_exceptions`/`flagged_transactions` (synced
into Postgres per Phase 1's import job) and start a process instance. Two options:

- **Polling worker** (simplest for a POC): a small scheduled job (Python, using the Zeebe client
  SDK) queries Postgres for records with no existing process instance and calls
  `CreateProcessInstance` for each. Runs on the same cadence as the Databricks→Postgres import.
- **Postgres LISTEN/NOTIFY + a worker subscribed to it** — lower latency, more moving parts than
  a POC needs.

**Recommendation: polling worker**, given the POC's nightly-batch cadence elsewhere in the
pipeline — a real-time trigger doesn't match the rest of the architecture's freshness guarantees
and adds complexity without a corresponding demo benefit.

## 5. Which Records Actually Get a Task

Not every flagged record necessarily needs a human review task — e.g. a `MISSING_RISK_RATING`
customer record might just need a data-entry fix, not a fraud investigation. For the POC scope,
**every row in `data_quality_exceptions` and `flagged_transactions` gets a task** (simplest
uniform rule), but this is worth revisiting once real volume is known — at scale, routing 100% of
exceptions to human review doesn't hold up, and some rule categories would need
auto-remediation or severity-based filtering instead (this is exactly what `validation_rules`'
`severity` field was for in the original source doc's design, currently unused here).

## 6. Acceptance Criteria

- [x] BPMN diagram/XML modeled (`camunda/process/transaction-review.bpmn`, hand-authored)
      implementing section 3's flow, all three candidate groups reachable
- [x] Local Camunda 8 stack deployable via one `docker compose up` (confirmed live — see
      `CLAUDE.md`)
- [x] A test process instance, started manually with sample variables (`camunda/bridge/test_instance.py`),
      routes to the correct candidate group based on `flagCategory` — confirmed live 2026-09-22
      against a deployed Zeebe/Tasklist: all three (FRAUD → `fraud-investigation`, COMPLIANCE →
      `compliance`, OPERATIONS → `operations`) showed up correctly in a real
      `POST /v1/tasks/search` response
- [x] Completing a task (Approved/Rejected/Corrected) triggers the write-back service task —
      confirmed live 2026-09-22: all three outcomes completed via Tasklist's REST API landed
      correctly in `review_outcomes` (`camunda/bridge/outcome_worker.py`), including a Corrected
      outcome's `{"risk_rating": "B"}` value round-tripping into `corrected_value`. Required two
      fixes along the way, both applied: (1) Windows' default asyncio event-loop policy breaks
      grpc.aio's streaming `ActivateJobs` call ("attached to a different loop") unless the
      Zeebe channel/worker are constructed inside the running loop, not at module import time;
      (2) Tasklist's real `/complete` request body is `{variables: [{name, value}]}` with each
      `value` JSON-encoded, not a plain `{name: value}` object.
- [x] Bridge worker (`camunda/bridge/poll_worker.py`) successfully creates a process instance from
      a real flagged record without manual intervention — confirmed live 2026-09-22 against
      Neon's real `flagged_transactions` (92 `VELOCITY_BREACH` rows, all real production data at
      the time; `data_quality_exceptions` was empty, so only the fraud path was exercised here).
      A second run started 0 new instances, confirming `camunda_process_tracking` makes this
      idempotent as designed.

## 7. Open Items

1. **Compliance routing rule** — resolved with a documented table-based assumption (section 3),
   not a verified business rule; confirm with whoever owns the process requirements
2. **Auth model** — **partially resolved by what the live stack actually requires, not a choice
   made here**: `ZEEBE_AUTHENTICATION_MODE=none` only disables auth on the Zeebe gRPC gateway.
   Tasklist's own webapp has a separate, always-on session-cookie login (Spring Security),
   seeded with a default `demo`/`demo` user - there's no way to turn this off short of wiring up
   Identity, which section 2 already ruled out for this POC. `frontend/src/workflow/tasklistApi.js`
   logs in as `demo`/`demo` automatically. Confirm with client stakeholders whether showing every
   reviewer the same generic `demo` identity (rather than their own login) is acceptable for the
   demo.
3. **"Corrected" outcome's data model** — what exactly can be corrected, and does the corrected
   value need its own validation before write-back (e.g. can't "correct" a `risk_rating` to an
   invalid value)?
