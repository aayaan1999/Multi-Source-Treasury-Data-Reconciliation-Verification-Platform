# Spec: CFO Reconciliation Workflow (FLOW-5)

**Status:** 5a (workflow) implemented 2026-09-24 — BPMN, bridge, outcome worker, migration 009,
backend endpoints, Tasks screen; Notebook 2 stores each rejected row's values. Tested locally
(pytest, vitest, load test); **the Camunda process has not been deployed or run against a live
stack, migration 009 is not yet on Neon, and Notebook 2's change has not run on a cluster.**
5b (Databricks applying approved corrections) is **not built** — see section 7.
**Backlog:** FLOW-5 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.
**Depends on:** `specs/pipeline-reconciliation.md` (FLOW-3 items), `specs/source-tagging.md`.

## 1. Objective

Step 5 of the flow agreed with the bank (2026-09-24): when the Reconciliation tab shows a gap, the
CFO investigates, handles it directly or reassigns it; the assignee updates values, comments and
submits back; the CFO gives final approval, and the database updates.

## 2. Decisions (placeholders to confirm)

| Decision | Choice for the demo | Why |
|---|---|---|
| Who is the CFO | The seeded **approver** user (`approver@bankx.demo`); set by `CFO_EMAIL` in the bridge | No new login or password reset; one setting to change |
| Which items go to the CFO | **Every** `OPEN` pipeline-reconciliation item with a gap, as agreed | The bottleneck concern (backlog) is a later threshold rule, not a blocker |
| Assign to people or teams | **Named people**, tracked in our app (`assigned_to`) | Camunda has one shared demo login, so per-person Camunda identity (Keycloak) is later work |
| What "update values" means | The assignee proposes corrections to fields of the **rejected records** behind the item | Those records are what made the gap |
| "Database updates" on approval | Immediately in Neon: item `APPROVED`, corrections `APPROVED`, audit rows. The numbers change after Databricks applies the corrections (5b) and the data is refreshed (FLOW-6 Refresh Now) | The nightly run rebuilds the data from Databricks, so a Neon-only change would be overwritten |

## 3. Process: `reconciliation-review` (Camunda 8)

```
Item found (bridge) ─► CFO review ──┬─ APPROVE ─────────────────────────────► write outcome ─► end
                                    └─ REASSIGN ─► Assignee update ─► CFO final review ─┬─ APPROVE ─► write outcome ─► end
                                                        ▲                               │
                                                        └──────────── RETURN ───────────┘
```

| Step | Camunda | Who | Completes with |
|---|---|---|---|
| CFO review | user task, group `cfo` | CFO | `cfoDecision` = `APPROVE` or `REASSIGN` (+ `assigneeUserId`) |
| Assignee update | user task, group `reconciliation-team` | the named assignee | nothing extra: corrections and comments are saved in our app first |
| CFO final review | user task, group `cfo` | CFO | `finalDecision` = `APPROVE` or `RETURN` |
| Write outcome | service task `write-reconciliation-outcome` | `outcome_worker.py` | marks item + corrections approved |

Separate from `transaction-review`: the handle/reassign/return loop would complicate the shared
single-review process used by fraud, data-quality and breach tasks.

A CFO may add corrections at "CFO review" before approving (handling it directly).

## 4. Data (migration 009)

- `pipeline_reconciliation`: status widened to `OPEN`, `MATCHED`, `WITH_CFO`, `ASSIGNED`,
  `SUBMITTED`, `APPROVED`; new `assigned_to`, `approved_by`, `approved_at`.
- New `reconciliation_corrections`: one proposed value per record field — `recon_id`,
  `source_table`, `record_key`, `field_name`, `old_value`, `new_value`, `entered_by`,
  `entered_at`, `status` (`PROPOSED` / `APPROVED`), `approved_by`, `approved_at`, `synced_at`
  (for 5b).
- `data_quality_exceptions.record_data` (jsonb): the rejected row's own values, written by
  Notebook 2, so the assignee can see what to fix — rejected rows are otherwise only in Delta.
- `camunda_process_tracking.record_type` widened with `reconciliation` (`source_table` =
  `pipeline_reconciliation`, `record_key` = `recon_id`, `flag_label` = `RECONCILIATION`), so the
  bridge never starts a second process for the same item.
- Comments reuse `comments` with the same key.

## 5. Status and audit

| Event | Status | Written by |
|---|---|---|
| Process started | `WITH_CFO` | bridge |
| CFO reassigns | `ASSIGNED`, `assigned_to` set | backend, called by the Tasks screen |
| Assignee submits | `SUBMITTED` | backend |
| CFO returns | `ASSIGNED` (same assignee) | backend |
| CFO approves | `APPROVED`, corrections `APPROVED` | outcome worker (authoritative), audit via backend |

Every event writes one `audit_log` row (`object_type` = `reconciliation_item`), and every
correction one more. The load stays insert-only, so a rerun never resets these statuses.

## 6. Acceptance criteria

- [x]/[ ] Bridge starts one `reconciliation-review` per OPEN gap item, never twice — implemented; not run against Camunda
- [x]/[ ] All three routes (approve directly; reassign → submit → approve; reassign → submit → return → submit → approve) — BPMN written; not run against Camunda
- [x] Corrections: only on a rejected record of this item, one open proposal per field, the old value kept (backend tests)
- [x] Status transitions and audit rows as in section 5, wrong-order actions refused (backend tests)
- [x] Outcome writer approves item + corrections in one transaction (unit-tested against Postgres)
- [x] Tasks screen: reconciliation tasks show the item, its rejected records, corrections and the step's actions (vitest)
- [ ] Deployed and run live; screen checked in a browser

## 7. Not in 5a: applying corrections (5b)

Approved corrections sit in `reconciliation_corrections` (`synced_at` null). 5b: Notebook 1 (or a
step before Notebook 2) reads them from Neon, patches the matching raw rows before the checks,
and marks them synced — so on the next run (or Refresh Now) the corrected records pass, the gap
closes, and the dashboard numbers include them. Until 5b, approval is recorded but the numbers
don't change.

## 8. Open items

1. Confirm the CFO login, and whether every item goes to the CFO or only above an amount.
2. A new run with the same broken record opens a new item and a new process (FLOW-3 open item 1).
3. Per-person access in Camunda needs an identity provider; today every demo user can see all tasks.
