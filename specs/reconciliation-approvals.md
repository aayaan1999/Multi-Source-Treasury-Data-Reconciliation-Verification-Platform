# Reconciliation approvals: team decides, CFO approves important tasks, CFO signs off each run

**Status:** Built and verified live on the local stack (2026-09-30): Camunda 8 (Zeebe + Tasklist), the bridge
workers, Neon and the app. Replaces the CFO-first `reconciliation-review` process
(`specs/cfo-reconciliation-workflow.md`, sections 3 and 5) and the per-group "second approval" and two-person
run sign-off of `specs/reconciliation-groups.md` (sections 3, 4 and 6). Plan agreed with the manager in the
"Reconciliation Tasks Plan" doc; its improvements (deadlines and escalation, a run progress bar, a sign-off
evidence pack) are **not built yet**.

## 1. Why

The Tasks tab had two kinds of reconciliation task that asked different people to do different things in a
different order: a pipeline gap went to the CFO first (review, reassign, update values, final review), a
core-system break group went to the team first (with a CFO "second approval" only for bulk groups of 100,000
or more). Run sign-off was a separate two-person form on the Reconciliation tab, not a task, and could be
submitted with work still open. Demo audiences found this hard to follow.

## 2. The model

| Level | When | Who | Two different people? |
|---|---|---|---|
| Team decision | Every task | The owning team (`recon.rules.owner_team`, Operations) | n/a |
| CFO approval | Important tasks and any data fix, straight after the team decides | CFO (approver) or admin | Yes: never the person who decided |
| Run sign-off | Once every task in the run is decided | CFO (approver) or admin | Yes: never anyone who decided a task in the run |

**Important** (the CFO approves whatever the team decides), placeholders in `app_settings['recon.rules']`:

- pipeline gap: a delivery that sent no rows, or a gap of `important_amount` (10,000) or more in one currency
- break group: a missing record, a key field (`important_fields`), a single difference of 10,000 or more, or a
  bulk group whose differences add up to 10,000 or more
- any task where the team chooses **Correct our data**

The three decisions are the same on both task types: **Accept** (the difference is explained),
**Correct our data** (fix our copy: the team enters values on a pipeline gap; on a group each kept record
gets a Fixed value, filled in with the source system's value and editable, sent as `correctedValues`;
the worker refuses an empty, non-numeric or unchanged value) and **Dismiss** (not a real problem). A group can leave records
out; each becomes a task of its own in the same run. A missing record can't be corrected from here.

## 3. Camunda

`camunda/process/reconciliation-task.bpmn` (both task types):

```
Team review ─► Save the decision ─► saved? ── no ──► Team review (decisionError)
 (teamGroup)                           │ yes
                                       ▼
                                  Important? ── no ──► Decided (waits for run sign-off)
                                       │ yes
                                       ▼
                     ┌──────────── CFO approval (cfo) ◄── refused (approvalError)
                     │ send back          │ approve            │
                     ▼                    ▼                    │
              Reopen for team      Save the approval ── ok? ───┘
              (sentBackNote)              │ yes
                     │                    ▼
                     └─► Team review   Approved
```

`camunda/process/reconciliation-run-signoff.bpmn`: Run sign-off (cfo) ─► Close the run (refused →
back with `signoffError`) or Reopen the named tasks (`sendBackTasks`).

Service tasks (all in `camunda/bridge/outcome_worker.py`) return the variables their gateway reads, so a
refused step goes back to the person with the reason instead of raising an incident:

| Job type | Does | Returns |
|---|---|---|
| `recon-record-decision` | checks and saves the team's decision (`recon_tasks_db.record_decision`) | `decisionOk`, `decisionError`, `needsCfo`, `cfoReason` |
| `recon-approve` | CFO role + not the decider, then applies it (`recon_tasks_db.approve`) | `approvalOk`, `approvalError` |
| `recon-send-back` | undoes the decision for the team (`recon_tasks_db.send_back`) | `sentBackNote` |
| `recon-close-run` | CFO role, every task decided, signer decided none (`recon_runs_db.close_run`) | `signoffOk`, `signoffError` |
| `recon-run-send-back` | reopens the named tasks (`recon_runs_db.send_back_run`) | `signoffOk`, `signoffError` |

The Tasks screen checks the same rules first (`frontend/src/reconciliation/reconTask.js`), but the
workers are the guard: every demo login can see every task (no per-person access in Tasklist yet).

## 4. Runs

`reconciliation_runs` (migration 021): one row per run of a source. A pipeline source's run is its newest
delivery (`ingest_batch_id`); a comparison source's run is its newest comparison date (breaks' `last_seen`).
Each poll, the bridge (`recon_runs_db.sync_runs`) files every task under its source's current run; undecided
tasks from an older open run move to the current one and the older run is `SUPERSEDED`. When a run is
`OPEN`, has no undecided task (an important one waiting for the CFO counts as undecided) and no break
still waiting for a group, the bridge starts its sign-off (`IN_SIGNOFF`). A comparison that turns up new
groups while its run is already in sign-off starts a follow-on run (`<date>#2`). Sending tasks back reopens
them in the same run (`OPEN` again); the run comes back for sign-off once they're decided.

## 5. Data (migration 021)

- `pipeline_reconciliation`: `decision`, `decided_by`, `decided_at`, `cfo_required`, `cfo_reason`, `run_id`,
  `title`; statuses `WITH_TEAM`, `AWAITING_CFO`, `DECIDED`, `APPROVED` (the retired `WITH_CFO`, `ASSIGNED`,
  `SUBMITTED` stay allowed for history).
- `reconciliation_groups`: `decided_at`, `approved_at`, `cfo_required`, `cfo_reason`, `run_id`, `title`;
  status `AWAITING_CFO`. A group's breaks are resolved when the decision takes effect (at the team's decision,
  or at the CFO's approval).
- `reconciliation_corrections`: `group_id` (a fix can belong to a break group; exactly one of `recon_id` /
  `group_id`); status `WITHDRAWN` for a fix the decision no longer uses. Notebook 1 applies `APPROVED`
  fixes by table, record key and field, whichever owns them.
- `reconciliation_runs`: `status` `OPEN` / `IN_SIGNOFF` / `SIGNED_OFF` / `SUPERSEDED`, `signed_by`,
  `signed_at`, `sign_note`. `reconciliation_signoffs` (the old two-person form) is no longer written.

Every step writes `audit_log` rows: `DECIDED`, `APPROVED`, `SENT_BACK`, `CORRECTION_APPROVED`, one per break
resolved, `RUN_SIGNED_OFF`, `RUN_SENT_BACK`, `SENT_BACK_AT_SIGNOFF`.

## 6. Screens

- **Tasks:** one "Reconciliation (all)" filter; types "Reconciliation: rows not loaded", "... data differs",
  "... run sign-off"; plain titles written by the bridge (e.g. "12 accounts: balance 9,000.00 lower in core
  banking"). One popup for all three (`ReconTaskPanel.jsx`): what happened and what to decide in sentences
  (`backend/app/recon_text.py`), the progress line (Team review → CFO approval, or "not needed" → Run
  sign-off, with who acts), the rows behind it with the bad field highlighted or our value beside the source
  system's with the difference, fixes, comments, and the step's buttons.
- **Reconciliation tab:** each source's current run and where its sign-off stands (read-only; the old
  submit / sign-off form is gone).
- Endpoints: `GET /reconciliation/runs`, `GET /reconciliation/runs/{id}`; `summary`, `run`, corrections and
  names added to `GET /reconciliation/pipeline/{id}/records` and `GET /reconciliation/groups/{id}`. Removed:
  `POST /reconciliation/run/submit`, `POST /reconciliation/run/signoff`, `POST /reconciliation/pipeline/{id}/events`,
  `GET /reconciliation/assignees`.

## 7. Demo reset

`python camunda/bridge/reset_reconciliation_demo.py --apply` (dry run without `--apply`; stop the poll worker
first): backs up the six reconciliation tables to `backup_recon_<timestamp>_*`, cancels every open
reconciliation process, reopens every decided break and each source's newest pipeline gaps, deletes groups
and runs, and writes one `DEMO_RESET` audit row. The next poll rebuilds the tasks: on the demo data, 3 pipeline
gaps and 15 break groups (11 core banking, 4 CRM), 12 of them needing the CFO.

## 8. Acceptance criteria

- [x] Both task types start with the team; important ones flagged for the CFO with the reason (backend tests; live)
- [x] Correct our data needs a value on a pipeline gap and is refused for a missing record, with the reason shown (backend + vitest; live)
- [x] A data fix always goes to the CFO (backend; live)
- [x] The CFO approval is refused for the person who decided and for anyone but the CFO or an admin, on the server (backend; live)
- [x] The CFO sends a decision back with a reason; the team sees it; a group's generated fixes are withdrawn (backend; live)
- [x] Leaving records out of a group makes each its own task in the same run (backend; live)
- [x] Sign-off starts only once every task in the run is decided, and is refused for anyone who decided a task (backend; live)
- [x] Sending named tasks back at sign-off reopens them in the same run and brings the run back for sign-off (backend; live)
- [x] The Tasks screen shows the sentences, rows, progress and buttons of each step (vitest)
- [ ] Checked in a browser against the live stack
- [ ] Notebook 1 applying a break group's approved fix (the value formats of `canonical_value` and the raw column must match) — not run in Databricks

## 9. Open items

1. The important rules and the 10,000 amount are placeholders to confirm with the bank.
2. Deadlines and escalation, a run progress bar and a sign-off evidence pack are planned, not built.
3. Per-person access in Camunda needs an identity provider; today every demo user sees every task.
