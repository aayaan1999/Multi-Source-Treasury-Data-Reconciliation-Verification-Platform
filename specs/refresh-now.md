# Spec: Refresh Now (FLOW-6)

**Status:** Implemented 2026-09-24 — `backend/app/routers/refresh.py`, `frontend/src/components/RefreshNow.jsx`
on the Executive Summary. Tested locally against a fake Jobs API; **not yet run against the real
Databricks job** (needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN` in `backend/.env`).
**Backlog:** FLOW-6 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.

## 1. Objective

Step 6 of the flow agreed with the bank (2026-09-24): data normally refreshes automatically; a
"Refresh Now" button lets the CFO update the live data right after reconciliation (e.g. once an
approved correction should reach the numbers — `specs/cfo-reconciliation-workflow.md` section 7)
without waiting for the next automatic run.

## 2. How it works

- `POST /api/v1/refresh` starts the `bank-data-pipeline` job through the Databricks Jobs API 2.1
  (`jobs/run-now`). CFO (the demo approver) and admin only; others get 403.
- Refused (409) while a run is already queued or running — the job runs one at a time anyway, and a
  second click shouldn't queue a duplicate refresh.
- Every request writes an `audit_log` row (`REFRESH_REQUESTED`, object `pipeline_job`, the run id).
- `GET /api/v1/refresh/status` returns the latest run: state, result, start/end time, what triggered
  it, and whether one is in progress. Anyone logged in can see it.
- The dashboard shows "Updated 10:51" (or "Refreshing… started 10:42"); the CFO/admin also get the
  button. While a run is going it polls every 15 s; when a run it was watching succeeds, the page
  reloads its numbers.
- **Not instant:** a full run takes minutes and uses Databricks compute. The label says so as it goes.

## 3. Configuration (`backend/.env`, never committed)

| Setting | Meaning |
|---|---|
| `DATABRICKS_HOST` | Workspace URL |
| `DATABRICKS_TOKEN` | Personal access token allowed to run the job |
| `DATABRICKS_JOB_ID` | Optional; otherwise the job is found by name |

Without host and token, the endpoints return 503 "isn't set up" and the CFO sees a one-line note —
nothing else in the app is affected. The token is only sent to Databricks: never logged, returned or
shown in an error.

## 4. The automatic refresh

A Databricks job has **one** trigger. It is currently *file arrival* (`databricks.yml`): the job
runs when a source delivers files, which is daily when sources deliver daily. A fixed "every 24 hours"
(`trigger.periodic`) would replace file arrival rather than add to it. **Open item: confirm which the
bank wants** — kept as file arrival until then, since the demo relies on it.

## 5. Acceptance criteria

- [x] CFO/admin can start a run; others can't (backend tests)
- [x] A second request while running is refused, not queued (backend tests)
- [x] Audited; token never leaked in an error (backend tests)
- [x] Dashboard label, button, polling, reload on success; hidden button for other roles (vitest)
- [ ] Run against the real job with a real token; checked in a browser
