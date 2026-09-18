# Spec: Notebook 3 — Nightly KPI Summary

**Status:** Spec only — not yet implemented
**Supersedes:** the treasury-specific "Reconciliation & Consolidated Report" design (aggregating
positions by entity/currency pair/position type) — that no longer applies now that Notebooks 1-2
ingest the bank-wide schema instead of treasury positions
**Source of truth:** `Middle East bank data cleaning and reporting.md`, Screen 1 section
("How it actually works underneath")
**File (planned):** `notebooks/03_kpi_summary.py`
**Depends on:** `specs/notebook-01-bank-data-ingestion.md`, `specs/notebook-02-bank-data-quality.md`
(reads their `{table}_clean` output)

---

## 1. Objective

Precompute the 8 Executive Summary (Screen 1) KPI values nightly, into one small summary table,
so the React frontend never computes them live on page load. This is an explicit, non-optional
performance requirement from the source doc: *"the screen reads from the pre-calculated summary,
not from millions of rows ... if you calculate live on the fly, the demo will feel slow."*

## 2. Why This Notebook Exists Here, Not in the Application Layer

`PLATFORM-BUILD-PLAN.md` assigns most nightly precomputation (e.g. `branch_performance_monthly`)
to the application layer's APScheduler jobs. This one KPI set is different: it reads directly
from Notebook 2's `{table}_clean` Delta tables, which only exist inside the Databricks workspace.
Computing it here keeps the FastAPI/PostgreSQL layer from needing its own Databricks connection
just to run eight aggregate queries — Postgres gets a small, already-computed row per day instead.

## 3. Scope

**In scope:** one row per calculation date in a `kpi_daily_summary` Delta table, covering the 5
of 8 Executive Summary KPIs that are actually computable from the current schema (see section 5).

**Explicitly out of scope:**
- `branch_performance_monthly` (Screen 5) — deferred to the application layer per
  `PLATFORM-BUILD-PLAN.md` Phase 4, not built here
- Scenario Modelling (Screen 4) — browser-side recompute against an in-memory snapshot, not a
  Databricks batch job, per the source doc's own architecture
- `calculation_audit` (Screen 3's drill-to-source) — that's an application-layer table populated
  when a *report* is generated, not a byproduct of this nightly batch job
- The 3 KPIs blocked by schema gaps (NIM, Cost-to-Income, ROE) — see section 6

## 4. Currency Conversion Requirement

`loans`, `accounts`, and `transactions` amounts are in each record's own `currency` column, not
one reporting currency — summing them raw across currencies (as the original treasury notebook's
design would have flagged as a bug) produces a meaningless number. **Every cross-currency
aggregate in this notebook must convert to USD first**, using the **most recent valid rate** per
currency pair from `fx_rates_clean` (Notebook 2's output — `INVALID_RATE`/`DUPLICATE_RATE` rows
are already excluded from it). This mirrors the original treasury notebook's FX-conversion
approach and is a hardcoded-rate POC simplification, not a live feed — same caveat as before.

## 5. KPIs Computable From the Current Schema

| KPI | Formula | Source table(s) |
|---|---|---|
| Capital Ratio (CAR) | `(tier1_capital + tier2_capital) / risk_weighted_assets × 100`, latest `month` row | `capital_positions_clean` |
| Liquidity Ratio (LCR) | `hqla / net_outflows_30d × 100`, latest `date` row | `liquidity_daily_clean` |
| NPL Ratio | `SUM(outstanding WHERE days_past_due >= 90) / SUM(outstanding) × 100` (USD-converted) | `loans_clean` |
| Total Assets | `SUM(loans.outstanding) + SUM(accounts.balance)` (USD-converted) — a simplified proxy, not a full balance-sheet total (no cash/investments/fixed-asset tables exist in the schema) | `loans_clean`, `accounts_clean` |
| Dollarization Ratio | `SUM(accounts.balance WHERE currency != 'LBP') / SUM(accounts.balance) × 100` (USD-converted) — assumes LBP is *the* local currency platform-wide, which only holds for a Lebanon-headquartered entity; **not correct if this platform is ever used for a bank without LBP as home currency** | `accounts_clean` |

## 6. KPIs Blocked by Schema Gaps (do NOT implement with a guessed formula)

These three are genuine gaps in the source doc's own database schema, not implementation
shortcuts — flagging them here rather than fabricating a number that would look authoritative
on a KPI tile but rest on an unstated assumption:

- **Net Interest Margin (NIM)** — "what we earn on loans minus what we pay on deposits."
  Interest earned on loans is computable (`SUM(outstanding × interest_rate)`, USD-converted).
  Interest **paid on deposits is not** — the `accounts` table has no interest-rate column. Needs
  either a new column on `accounts` or a separate deposit-rate table before this is computable.
- **Cost-to-Income** — needs branch cost (`branches.monthly_opex`) alongside revenue.
  `branches` has **no currency column**, so it's unknown what currency `monthly_opex` is
  denominated in — can't safely combine it with USD-converted revenue. Needs either a
  `branches.currency` column or an explicit statement that opex is always reporting-currency.
- **Return on Equity (ROE)** — needs `profit` (blocked transitively by Cost-to-Income's gap,
  since profit = revenue − cost) and a `shareholders' equity` figure the schema doesn't define
  anywhere (`tier1_capital` is a plausible proxy but that's an accounting judgment call, not
  something to assume silently).

**Recommendation:** raise these three gaps with whoever owns the source-of-truth doc before
Screen 1 is built — Screen 1's design assumes all 8 tiles are populated. Until resolved, `kpi_daily_summary`
should store these three columns as `NULL`, not a wrong or approximated number.

## 7. Output

Delta table `kpi_daily_summary`:

| Column | Type | Notes |
|---|---|---|
| `calculation_date` | date | the run date, not a source-data date |
| `car_pct` | double | |
| `lcr_pct` | double | |
| `npl_ratio_pct` | double | |
| `total_assets_usd` | double | |
| `dollarization_ratio_pct` | double | |
| `nim_pct` | double | always `NULL` until section 6's gap is resolved |
| `cost_to_income_pct` | double | always `NULL` until section 6's gap is resolved |
| `roe_pct` | double | always `NULL` until section 6's gap is resolved |

## 8. Acceptance Criteria

- [ ] All 5 computable KPIs match the hand-traced values in section 9 when run against
      `bank-data/*.csv`
- [ ] `nim_pct`, `cost_to_income_pct`, `roe_pct` are `NULL`, not a fabricated number
- [ ] Currency conversion uses the latest *valid* (post-Notebook-2) rate per pair, not a raw
      `raw_fx_rates` row that might be an excluded duplicate/invalid rate
- [ ] Running twice against the same `{table}_clean` state produces the same output (idempotent
      overwrite of the day's `kpi_daily_summary` row, not an ever-growing duplicate)
- [ ] Not yet implemented — this spec exists to define scope before writing the notebook code

## 9. Traceability (hand-computed against `bank-data/*.csv`, latest-rate assumptions per section 4)

Using latest clean FX rates: USD/LBP 89600 (2026-09-16), USD/SAR 3.75 (2026-09-15, since both
2026-09-16 rows are excluded as `DUPLICATE_RATE`), USD/QAR 3.64 (2026-09-16), EUR/USD 1.10
(2026-09-17).

| KPI | Expected value | Basis |
|---|---|---|
| CAR | ≈ 12.39% | Latest clean `capital_positions` row (2026-07): (207,000,000 + 39,000,000) / 1,985,000,000 × 100 |
| LCR | ≈ 144.66% | Latest clean `liquidity_daily` row (2026-09-17): 515,000,000 / 356,000,000 × 100 |
| NPL Ratio | ≈ 23.83% | Clean loans total outstanding (USD-converted) ≈ 2,098,462; NPL (L003, already USD) 500,000 |
| Total Assets | ≈ 2,779,838 USD | Clean loans outstanding (≈2,098,462) + clean accounts balance (≈681,376), all USD-converted |
| Dollarization Ratio | ≈ 99.98% | Only `ACC002` is LBP (≈167 USD-equivalent) out of ≈681,376 USD total — illustrates how hyperinflated LBP naturally pushes dollarization near 100%, consistent with the real post-2019 Lebanon context the source doc references |

These are hand-computed, not verified by an actual run — treat as the test plan to check against
real notebook output once implemented and run on a live cluster, same caveat as Notebooks 1-2's
specs.

## 10. Non-Goals

- No historical backfill — this notebook computes today's snapshot only; a 24-month trend (which
  Screen 1's UI needs) comes from `kpi_daily_summary` accumulating one row per day over time, not
  from this notebook computing history in one run
- No alert-strip text generation (Screen 1's "Capital ratio at 12.4% — only 0.4 points above
  minimum") — that's presentation logic in the application layer, not this notebook
