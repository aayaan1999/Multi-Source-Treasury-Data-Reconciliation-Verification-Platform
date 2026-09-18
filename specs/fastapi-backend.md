# Spec: FastAPI Backend

**Status:** Spec only — not yet implemented
**Plan reference:** `PLATFORM-BUILD-PLAN.md` Phase 1, `3-WEEK-POC-PLAN.md` Track A/C
**Depends on:** `specs/postgres-schema.md`
**Consumed by:** React frontend (all 6 screens), the Camunda bridge worker (indirectly, via
Postgres)

---

## 1. Objective

The API layer between PostgreSQL and the React frontend. Read-heavy (dashboards) plus a small
set of write endpoints (comments, manual overrides) — **the actual approval/task actions
themselves go through Camunda's Tasklist API directly from React**, not through this backend, per
`CLAUDE.md`'s Workflow Engine Decision. Don't build a duplicate workflow-action API here.

## 2. Endpoint Groups (one per screen, plus shared)

### 2.1 Screen 1 — Executive Summary
- `GET /api/v1/kpi-summary/latest` — most recent `kpi_daily_summary` row, including
  `assumptions_applied` so the frontend knows which tiles need a footnote
  (`specs/notebook-03-kpi-summary.md` section 7)
- `GET /api/v1/kpi-summary/history?days=30` — trend data (returns however many days actually
  exist — 1 for a fresh demo, per that spec's non-goals)

### 2.2 Screen 2 — Portfolio & Credit Risk
- `GET /api/v1/portfolio/breakdown?dimension={product|segment|branch|currency}` →
  `loan_breakdown_by_dimension`
- `GET /api/v1/portfolio/stage-summary` → `loan_stage_summary`
- `GET /api/v1/portfolio/top-exposures` → `top_exposures`
- `GET /api/v1/portfolio/ageing` → `loan_ageing_summary`
- `GET /api/v1/portfolio/ltv-distribution` → `ltv_distribution`
- `GET /api/v1/portfolio/loans?filter=...` — drill-down query directly against `loans`, backing
  the "click a bar, see the loan list" interaction from the source doc

### 2.3 Screen 3 — Regulatory Reporting
- `GET /api/v1/reports` → `report_instances` list (calendar view)
- `GET /api/v1/reports/{id}` → `report_line_items` for one report
- `GET /api/v1/reports/{id}/drill/{line_code}` → `calculation_audit` entry (formula, source
  tables, record count, timestamp) — this is the single most important endpoint per the source
  doc's own framing of drill-to-source as the standout feature
- `POST /api/v1/reports/{id}/export/pdf`, `POST /api/v1/reports/{id}/export/excel` — ReportLab/
  openpyxl generation, for the one template in scope (Capital Adequacy, per
  `3-WEEK-POC-PLAN.md`'s shallow scope)

### 2.4 Screen 4 — Scenario Modelling
- `GET /api/v1/scenario/snapshot` → `scenario_snapshot` (the ~50-number payload,
  `specs/notebook-06-portfolio-branch-scenario-snapshot.md`), fetched **once** on screen load
- `POST /api/v1/scenario/save` — persists a named scenario (base/adverse/severe or custom) with
  its 4 input values and computed outputs, for the "compare scenarios side by side" table
- **Explicitly not an endpoint**: the actual slider recompute. That happens entirely client-side
  in React against the fetched snapshot, per the source doc's hard performance requirement — no
  endpoint should exist that recomputes on every slider tick

### 2.5 Screen 5 — Branch & Segment Performance
- `GET /api/v1/performance/branches` → `branch_performance_summary`
- `GET /api/v1/performance/segments` → `segment_performance_summary`
- `GET /api/v1/performance/products` → `product_performance_summary`

### 2.6 Screen 6 — Report Workflow
- `GET /api/v1/exceptions?status=...` — reads `data_quality_exceptions` +
  `flagged_transactions` joined with Camunda task state (fetched server-side from Tasklist's API
  and merged, or the frontend calls Tasklist directly — **decide this once Camunda integration is
  built**, don't guess now)
- `POST /api/v1/exceptions/{id}/comments` — writes to `comments`, mirrored into `audit_log`
  (insert-only, enforced at the DB grant level per `CLAUDE.md`)
- **Approve/reject/correct actions themselves**: React → Camunda Tasklist API directly (section 1)

### 2.7 Shared
- `POST /api/v1/auth/login` — against the four seeded demo users (analyst/reviewer/approver/admin)
- `GET /api/v1/health` — for demo-environment sanity checks before a live run

## 3. Auth

Four seeded users, per `CLAUDE.md`. Simple JWT or session-based auth is sufficient for a POC —
**do not build Keycloak/SSO integration**, explicitly deferred per the same decision.

## 4. What This Backend Does NOT Do

- No business logic duplicated from the notebooks — every number served here was already computed
  by Databricks (or, for Screen 4, computed client-side from a fetched snapshot). This API is a
  read/query layer over precomputed Gold-layer tables, not a second calculation engine.
- No direct Camunda process manipulation beyond what's explicitly listed (task actions go
  React→Tasklist directly)

## 5. Acceptance Criteria

- [ ] Every screen's read endpoints return data matching their source table's spec exactly (same
      "don't drift from the Databricks/Postgres schema" principle as `specs/postgres-schema.md`)
- [ ] `GET /api/v1/scenario/snapshot` responds fast enough that the frontend's subsequent
      slider interactions genuinely never call the backend again
- [ ] `POST /api/v1/reports/{id}/export/pdf` produces a file matching the source doc's worked
      Capital Adequacy example layout
- [ ] Not yet implemented

## 6. Non-Goals

- No GraphQL (REST is sufficient for this scope)
- No API versioning strategy beyond a `/v1/` prefix (no `/v2/` planned, not worth designing for)
- No rate limiting / production hardening (POC scope)
