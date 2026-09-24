# Spec: Breach Levels, Consecutive Days, Deadlines, One Set of Limits (client point 8: BRC-1..4)

**Status:** Implemented 2026-09-24 — `db/migrations/014_breach_levels.sql`, `camunda/bridge/breaches_db.py`
(used by `breach_check.py`), `GET /api/v1/kpi-summary/limits`, tiles reading limits after login.
Tested locally; **not yet run against Camunda or Neon.**
**Backlog:** BRC-1..4 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.

## 1. Problem

A breach was one line per KPI crossed on one day: no levels, no "breached N days running", no
deadline, and the dashboard tiles kept their own copy of the thresholds, which could disagree with
the breach check.

## 2. Three levels per limit (BRC-1)

| Level | Column | What happens |
|---|---|---|
| Early warning | `limits.early_warning_value` | Breach recorded as `WARNING` — a notification, **no task, no deadline**; clears itself when the KPI recovers |
| Internal appetite | `limits.threshold_value` | Breach `OPEN` → Compliance task, due in `resolution_days` |
| Regulatory | `limits.regulatory_value` | Breach `OPEN` → urgent Compliance task (severity High), due in half the days (min 1) |

Seeded for every KPI tile from the dashboard's former built-in thresholds (amber → early warning,
red → appetite, the chart's limit line → regulatory where there is one). An existing limit keeps its
threshold. **All placeholders** (`is_placeholder`) until the bank gives official values.

## 3. Consecutive days (BRC-2)

`limits.consecutive_days` (default 1). A breach counts only if the KPI was past the level on each of
the last N daily KPI rows; the level recorded is the one held on **every** one of those days (the
least severe of them). A missing day means "not yet".

## 4. One open breach per limit, escalating (BRC-1/3)

- No open breach and a level is crossed → new breach at that level.
- An open breach at a lower level → the **same** breach is escalated (level, value, due date; a
  WARNING becomes OPEN once it reaches appetite), with an `ESCALATED` audit row. Never a second
  open breach for the same limit, so never a duplicate task.
- Back within all levels → an early warning clears itself (`CLEARED`); a breach with a task stays
  open until a person resolves it.

## 5. Deadlines (BRC-3)

`breaches.due_date` from the level (section 2). Passed to Camunda as `dueDate`; the Tasks list shows
it with Overdue, like every other task (`specs/task-cases.md`). The breach task's Record cell names
the line crossed ("regulatory limit 12.00%" or "limit 12.50%").

## 6. One set of limits (BRC-4)

`GET /api/v1/kpi-summary/limits` returns every KPI's levels; after login the app applies them to the
shared KPI config, so tiles, trend lines, alerts, KPI detail and portfolio all use the numbers the
breach check uses. If they can't be loaded, the built-in values stay (the app never blocks on it).
The Capital Adequacy return's minimum is the regulatory level (else the threshold), so its "buffer
above the regulatory minimum" line still reads 12%.

## 7. Acceptance criteria

- [x] Levels, consecutive days, escalation without duplicates, warnings as notifications that clear (backend tests)
- [x] Due dates per level; only OPEN breaches become tasks (backend tests)
- [x] Tiles use database limits; fallback kept (vitest); capital report still uses 12% (existing tests)
- [ ] Run live: migration 014 on Neon, breach_check against Camunda
