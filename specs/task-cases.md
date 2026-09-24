# Spec: Task Cases, Severity, Deadlines and Policy (client point 6: TSK-1..4)

**Status:** Implemented 2026-09-24 — `db/migrations/012_task_cases_and_settings.sql`,
`camunda/bridge/cases_db.py` (+ poll/outcome workers), backend endpoints, Tasks screen. Tested
locally; **not yet run against Camunda or Neon.**
**Backlog:** TSK-1..4 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md` (point 6).

## 1. Problem

Every flag became its own task: the 2026-09-24 run's 94 Suspicious flags would be 94 tasks, and one
incident (3 same-day transactions on one account, each hit by two rules) made 6. Tasks had no
priority and no deadline.

## 2. Cases (TSK-1)

Pending transaction flags (`flagged_transactions`, status `PENDING_REVIEW`, not yet in a case) are
grouped by **account + transaction date + flag type** (Suspicious / Threshold / Operational). Flag
type decides the team (`poll_worker.flag_category`), so every case belongs to exactly one team.

- `task_cases`: one row per case — account, date, flag type, team, severity, score, flag count,
  due date, status (`PENDING` → `OPEN` once its task exists, `DIGEST` for low severity, `CLOSED`
  when decided), outcome, process key.
- `task_case_flags`: which flags are in which case. A flag is only ever in one case.
- One `transaction-review` process per case (same BPMN, same team routing), with
  `recordType = "fraud_case"`, `recordKey = case_id`, a one-line `title`
  ("ACC005 · 9 Sep 2026 · 6 flags"), `severity` and `dueDate`.
- Per-flag rows still go into `camunda_process_tracking`, so a flag can never also get a task of
  its own.
- A new flag arriving after its account/day's case has a task opens a **new** case (a task under
  review is never changed).
- The decision (Approved / Rejected) applies to every flag in the case: each flag's status is
  updated and gets its own `review_outcomes` row. "Corrected" stays a single-record action.
- Data-quality exceptions, breaches and reconciliation items stay one task each (agreed).

## 3. Severity (TSK-2)

`app_settings['task.severity']`, placeholder until the bank signs off:

| Part | Default |
|---|---|
| Base score by flag type | Suspicious 3, Threshold 2, Operational 1 |
| +1 | the case has 3 or more flags |
| +1 | the case has 2 or more different rules |
| Level | High ≥ 4, Medium ≥ 2, Low below |

High and Medium cases become tasks; **Low goes to the daily digest** — listed on the Tasks screen,
no task, and "Raise as task" turns one into a task (the bridge starts it next poll).

## 4. Deadlines (TSK-3)

`app_settings['task.due_days']`: High 2 days, Medium 5, Low 10, data quality 5, reconciliation 3.
Breaches use their limit's `resolution_days` (point 8). A case's due date is stored on the case and
passed to Camunda as `dueDate`; other tasks' due dates are their creation date + the days. The
Tasks list shows Severity and Due, flags **Overdue** in red, and sorts overdue first, then by
severity and due date.

## 5. Policy (TSK-4)

`GET /api/v1/workflow/policy` returns the settings; the Tasks screen shows "How tasks are created"
in plain words built from them (what makes a case, severity, what goes to the digest, deadlines,
who gets what). Every value is marked as a placeholder until the bank confirms it.

## 6. Settings table (`app_settings`)

Shared by points 5, 6 and 8: `key`, `value` (jsonb), `description`, `is_placeholder`,
`updated_at`. Seeded by migration 012 with the defaults above; changing a value changes behaviour
without code changes.

## 7. Acceptance criteria

- [x] Flags group into one case per account + day + type; each flag in exactly one case (tests)
- [x] Severity and digest routing per section 3 (tests)
- [x] Case decision updates every flag + review_outcomes per flag, once (tests)
- [x] Tasks list: severity, due, overdue first; case popup lists its flags; digest + raise; policy panel (vitest)
- [ ] Run live against Camunda and Neon
