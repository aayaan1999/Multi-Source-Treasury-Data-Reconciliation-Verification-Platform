# Spec: CFO Dashboard — By Country (FLOW-4)

**Status:** Implemented 2026-09-24 — `country_performance_summary` in Notebook 6, the load,
`db/migrations/010_country_performance_summary.sql`, `GET /api/v1/kpi-summary/countries`, and a
"By country" section on the Executive Summary. Backend, frontend and load logic tested locally;
**Notebook 6's change is not yet run on a cluster, migration 010 is not yet on Neon.**
**Backlog:** FLOW-4 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.
**Depends on:** `specs/source-tagging.md` (each record's `source_country`).

## 1. Objective

Step 4 of the flow agreed with the bank (2026-09-24): the CFO sees aggregated KPIs and a global
financial summary across all countries, not just bank-wide totals.

## 2. What's shown

One row per country, latest day, biggest loan book first, then a **bank-wide** row:

| Column | From | Notes |
|---|---|---|
| Customers | `customers_clean` | distinct customers |
| Deposits | `accounts_clean.balance`, in USD | same meaning as the branch/segment tables' deposits |
| Loans | `loans_clean.outstanding`, in USD | |
| Share of loans | computed on screen | the country's loans / the bank's |
| Bad loans | loans 90+ days past due / loans | same 90-day rule as the NPL tile |
| Transactions, Volume | `transactions_clean`, volume = sum of absolute amounts in USD | activity, so withdrawals count |

The bank-wide row is summed on screen (every figure is USD, so they add up) and its bad-loan ratio
is recomputed from the sums, never averaged across countries. Capital and liquidity ratios stay on
the KPI tiles: they're bank-wide figures with no country.

## 3. Country and currency

- **Country** = FLOW-1a's `source_country`: the source's country for a single-country source, or
  the record's branch region for today's multi-country CSV set. Records whose branch can't be found
  show as `Unknown`; data loaded before tagging shows entirely as `Unknown`.
- **Reporting currency: USD**, converted at the day's live rates like every other Gold table in
  Notebook 6. **Open item: question 5 for the bank** (the agreed flow's example used ₹) — changing
  it means converting to another currency in Notebook 6, not a screen change.

## 4. Robustness

The load skips a snapshot table Neon doesn't have yet, so Notebook 6 can be deployed before or after
migration 010 (`db/test_load_logic.py`, load 8). The dashboard loads the country view separately, so
the rest of the page still shows if it isn't there yet; it also reloads after Refresh Now.

## 5. Acceptance criteria

- [x]/[ ] Notebook 6 writes one row per country per day with the columns above — implemented; not run on a cluster
- [x] Load: loaded like the other snapshots; skipped, not failed, before migration 010 (load test)
- [x] API: latest day only, biggest loan book first; empty before the first run (backend tests)
- [x] Screen: bank-wide row from sums, shares of loans (vitest)
- [ ] Run live; checked in a browser
