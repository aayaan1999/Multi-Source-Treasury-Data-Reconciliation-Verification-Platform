# Spec: Notebook 6 — Portfolio, Branch & Scenario Snapshot

**Status:** Spec only — not yet implemented
**New for:** the "no cuts, all 6 screens" revision of `3-WEEK-POC-PLAN.md` — flagged there as
needing its own spec before Track A builds it
**Source of truth:** `Middle East bank data cleaning and reporting.md`, Screen 2 / Screen 4 /
Screen 5 sections
**File (planned):** `notebooks/06_portfolio_branch_scenario_snapshot.py`
**Depends on:** `specs/notebook-02-bank-data-quality.md` (`{table}_clean` outputs) only — **does
not depend on Notebook 3**, deliberately, so Notebooks 3 and 6 can be built in parallel within
Track A (both just read Notebook 2's clean tables independently)

---

## 1. Objective

Precompute the Gold-layer aggregates Screens 2 (Portfolio & Credit Risk), 4 (Scenario Modelling),
and 5 (Branch & Segment Performance) need, so none of those screens compute live on page load —
same non-negotiable performance requirement as Notebook 3.

## 2. Shared Methodology (reused from Notebook 3, not re-derived)

- **Currency conversion**: latest valid rate from `fx_rates_clean`, same as
  `specs/notebook-03-kpi-summary.md` section 4.
- **`REGION_CURRENCY` map** (branch opex currency assumption) — same map defined in
  `specs/notebook-03-kpi-summary.md` section 6: `{"Beirut": "USD", "North": "USD", "South": "USD",
  "KSA": "SAR", "Qatar": "QAR"}`.
- Every ratio/aggregate that comes out looking implausible on `bank-data/*.csv` (this notebook has
  several, same as Notebook 3's cost-to-income/ROE) is a **sample-size artifact** — 5 clean loans
  and 2-3 customers per branch can't produce realistic ratios against branch-scale opex figures.
  Flagging this once here rather than repeating it per table below.

## 3. New Assumptions Introduced by This Notebook

- **`PRODUCT_RATE_TYPE`** (for Screen 4's "rate type" slicing, which needs a
  `floating_rate_flag` the schema doesn't have — same category of gap as Notebook 3's
  deposit-rate/branch-currency ones): `{"Mortgage": "fixed", "Personal": "fixed", "SME":
  "floating", "Corporate": "floating"}` — retail-style lending conventionally fixed-rate,
  commercial lending more often floating/negotiated. **Assumption, not sourced from the schema or
  the brief — confirm with the client.**
- **`ACCOUNT_RATE_TYPE`**: `{"Current": "floating", "Savings": "floating", "Term deposit":
  "fixed"}` — a term deposit locks a rate for its term; current/savings typically float with a
  reference rate. Same caveat.
- **`SEGMENT_COST_ALLOCATION`**: the source doc's Screen 5 segment-performance table includes a
  "Profit" column, but nothing in the schema attributes branch operating cost to a *segment*
  (only to a *branch*). Resolved by pro-rating each branch's `monthly_opex` across its segments
  proportional to that segment's share of (loans + deposits) at that branch. **This is a real
  modeling choice, not a neutral default — flag it clearly in the UI ("cost allocated
  proportionally, not measured") rather than presenting segment profit as a hard number.**

## 4. Output Tables

### `loan_breakdown_by_dimension` (Screen 2, section 2)

One row per `(dimension_type, dimension_value)`: `dimension_type` ∈ `{product, segment, branch,
currency}`, plus `total_outstanding_usd` and `bad_loan_outstanding_usd` (days_past_due ≥ 90) —
the source doc explicitly wants both bars per category, not just totals ("showing only totals
hides exactly what the screen exists to reveal").

### `loan_stage_summary` (Screen 2, section 4)

`stage`, `loan_count`, `outstanding_usd`, `provisions_usd`, `coverage_pct`
(`provisions_usd / outstanding_usd × 100`).

### `top_exposures` (Screen 2, section 5)

Top 20 by `SUM(outstanding_usd)` per `customer_id`: `customer_id`, `customer_name`,
`outstanding_usd`, `product`, `days_past_due`, `pct_of_capital` (`outstanding_usd / (tier1_capital
+ tier2_capital) × 100`, using the latest `capital_positions_clean` row — capital figures are
assumed already in reporting currency, no conversion, since they're top-of-house regulatory
figures with no `currency` column in the schema).

### `loan_ageing_summary` (Screen 2, section 6)

`bucket` ∈ `{Current, 1-30, 31-60, 61-90, 90-180, 180+}` (bucketed on `days_past_due`),
`outstanding_usd`, `pct_of_book`.

### `ltv_distribution` (Screen 2, section 7)

`bucket` ∈ `{<50%, 50-80%, 80-100%, >100%}` on `outstanding / collateral_value`. **A
`collateral_value` of 0 against nonzero `outstanding` is bucketed as `>100%`** (infinite/undefined
LTV treated as fully uncovered, consistent with the source doc's own framing: "anything above
100% is uncovered exposure").

### `branch_performance_summary` (Screen 5, sections 2-3)

`branch_id`, `region`, `deposits_usd`, `loans_usd`, `revenue_usd` (interest income + fee income,
same formula as Notebook 3 section 6's cost-to-income), `cost_usd` (`monthly_opex` via
`REGION_CURRENCY`), `profit_usd`, `cost_to_income_pct`, `staff_count`, `profit_per_staff_usd`.
Regional rollup is a `GROUP BY region` on this same table done at read time (application layer),
not a separate notebook output.

### `segment_performance_summary` (Screen 5, section 4)

`segment`, `customer_count`, `deposits_usd`, `loans_usd`, `revenue_usd`, `bad_loans_usd`,
`profit_usd` (via `SEGMENT_COST_ALLOCATION`, section 3), `revenue_per_customer_usd`.

### `product_performance_summary` (Screen 5, section 5)

`product`, `outstanding_usd`, `avg_interest_rate`, `interest_income_usd`, `npl_pct`,
`net_contribution_usd` (`interest_income_usd − provisions_usd` — this one needs **no** new
assumption, it's directly computable from `loans_clean.provision_amount`).

### `scenario_snapshot` (Screen 4)

**Single row**, nested-map columns, refreshed nightly, fetched once by the React app on Screen 4
load (per the source doc's explicit "pull today's position into memory once" performance
requirement):

| Column | Type | Contents |
|---|---|---|
| `loans_by_currency` | map\<string, double\> | outstanding USD, keyed by native currency |
| `loans_by_product` | map\<string, double\> | outstanding USD, keyed by product |
| `loans_by_rate_type` | map\<string, double\> | outstanding USD, keyed by `PRODUCT_RATE_TYPE` |
| `deposits_by_type` | map\<string, double\> | balance USD, keyed by account type |
| `deposits_by_rate_type` | map\<string, double\> | balance USD, keyed by `ACCOUNT_RATE_TYPE` |
| `tier1_capital_usd`, `tier2_capital_usd`, `risk_weighted_assets_usd` | double | latest `capital_positions_clean` row |
| `hqla_usd`, `net_outflows_30d_usd`, `stable_funding_usd`, `required_funding_usd` | double | latest `liquidity_daily_clean` row |
| `current_npl_pct`, `current_coverage_pct` | double | from `loan_stage_summary`, bank-wide |
| `current_avg_interest_rate` | double | weighted average across `loans_clean` |

## 5. Acceptance Criteria

- [x] Written: `notebooks/06_portfolio_branch_scenario_snapshot.py`. **Not yet run against a
      live cluster** — none of the below is verified by an actual run.
- [ ] All values in section 6 (traceability) match a real run against `bank-data/*.csv`
- [x]/[ ] `loan_ageing_summary` bucket boundaries — implemented with `<` on the upper edge of
      each bucket (a loan at exactly 30/90/180 days falls into the lower bucket); not yet
      verified against a live run
- [x]/[ ] Zero-collateral loans — implemented as an explicit `>100%` bucket assignment before the
      ratio is computed, avoiding a divide-by-zero; not yet verified
- [x]/[ ] `scenario_snapshot` always has exactly one row — implemented via `mode("overwrite")`
      on a single-row DataFrame each run; not yet verified
- [x]/[ ] Currency conversion superseded by `specs/fx-realtime-ingestion.md`: uses
      `fx_utils.get_live_rate()`, not `fx_rates_clean`, same as Notebook 3 — not yet verified

## 6. Traceability (hand-computed against `bank-data/*.csv`'s 5 clean loans: L001, L002, L003,
L005, L007 — full depth here since this is the most formula-heavy output; branch/segment/product
tables are lighter-traced, formulas are what matters there, not exact figures on this tiny sample)

**`loan_stage_summary`:**

| stage | loan_count | outstanding_usd | provisions_usd | coverage_pct |
|---|---|---|---|---|
| 1 | 3 (L001, L002, L005) | 1,560,000 | 15,600 | 1.0% |
| 2 | 1 (L007) | ≈38,462 | ≈1,923 | 5.0% |
| 3 | 1 (L003) | 500,000 | 250,000 | 50.0% |

**`top_exposures`** (all 5 clean loans, since well under 20), ranked by `outstanding_usd`:
C001 (800,000), C003 (500,000), C005 (480,000), C002 (280,000), C007 (≈38,462).
`pct_of_capital` for C001: `800,000 / 246,000,000 × 100 ≈ 0.33%` (2026-07 capital: tier1
207,000,000 + tier2 39,000,000) — nowhere near a realistic single-borrower breach on this sample,
another scale artifact.

**`loan_ageing_summary`:**

| bucket | outstanding_usd |
|---|---|
| Current (dpd=0) | 1,280,000 (L001 + L005) |
| 1-30 | ≈318,462 (L002 dpd=15, L007 dpd=30) |
| 31-60, 61-90, 180+ | 0 |
| 90-180 | 500,000 (L003, dpd=120) |

**`ltv_distribution`:**

| loan | collateral | outstanding | LTV | bucket |
|---|---|---|---|---|
| L001 | 1,200,000 | 800,000 | 66.7% | 50-80% |
| L002 | 350,000 | 280,000 | 80.0% | 80-100% |
| L003 | 400,000 | 500,000 | 125% | >100% |
| L005 | 2,500,000 | 1,800,000 (SAR, same-currency ratio, no conversion needed) | 72.0% | 50-80% |
| L007 | 100,000 | 140,000 (QAR, same-currency ratio) | 140% | >100% |

**`branch_performance_summary`, spot-check for B01 (Beirut, clean customers C001 + C002 only —
C009 excluded, `INVALID_SEGMENT`):** deposits ≈250,167 USD, loans 1,080,000 USD, revenue (interest
only, no fee income for these accounts) 64,600 USD, cost (opex, USD region) 210,000 USD, profit
≈-145,400 USD, cost-to-income ≈325%, staff 42, profit/staff ≈-3,462 USD. Same "unrealistic on tiny
sample" caveat as Notebook 3's bank-wide cost-to-income.

These are hand-computed, not verified by an actual run — same caveat as every other spec in this
repo.

## 7. Non-Goals

- No historical trend for any of these tables (single current snapshot only, per
  `3-WEEK-POC-PLAN.md`'s per-screen shallow scope)
- No customer-level LTV/ageing drill-down beyond what's needed for the top-20/ageing/LTV tables
  themselves (Screen 2's "click through to loan list" drill-down is an application-layer query
  against `loans_clean` directly, not a notebook output)
