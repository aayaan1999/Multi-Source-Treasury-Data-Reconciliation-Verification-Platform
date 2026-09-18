# Spec: Screen 4 — Scenario Modelling

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` Track C ("start here — most self-contained")
**Depends on:** `specs/notebook-06-portfolio-branch-scenario-snapshot.md` section 4
(`scenario_snapshot`), `specs/fastapi-backend.md` section 2.4

---

## 1. Objective

The "what-if" screen — least compromised by this POC's shallow-scope cuts, since the source doc's
own architecture (fetch once, compute client-side) is inherently light on backend/historical-data
dependencies that constrain other screens.

## 2. Layout

Split screen: **left = 4 sliders**, **right = results**, no "calculate" button — every slider
move updates the right side instantly.

- **Sliders**: currency devaluation (0-50%), interest rate change (±5%), bad loans increase
  (0-15%), deposit outflow (0-30%)
- **Presets**: Base / Adverse / Severe buttons setting all 4 sliders at once (illustrative
  starting values per the source doc — e.g. Adverse ≈ 20% devaluation, +2% rates, +5% NPL, 10%
  outflow; confirm real preset values with the client rather than treating these as final)
- **Results, top**: 4 boxes (capital ratio, liquidity ratio, capital surplus/shortfall, profit
  impact), each showing before/after/change, coloured against the regulatory minimum
- **Waterfall chart**: today's ratio → step down per stressed factor → final ratio
- **12-month projection**: capital ratio by month under stress, regulatory minimum as a dotted
  line, highlighting the crossing-point month if the minimum is breached
- **Comparison table**: saved scenarios side by side (Base/Adverse/Severe/custom)

## 3. Client-Side Calculation Engine (the core of this screen)

On load: `GET /api/v1/scenario/snapshot` **once**. Every subsequent slider move recomputes purely
in the browser against that fetched snapshot — **never calls the backend again per slider tick**,
per the source doc's hard performance requirement.

Calculation order (from the source doc, don't reorder — these interact):
1. Currency devaluation → revalue foreign-currency loan book (`new_value = outstanding × (1 + X)`)
2. → apply extra-default stress from devaluation (illustrative POC rule: 20% devaluation → +3-5%
   of foreign-currency loans default; **make this assumption visible/editable in an "Assumptions"
   panel, not buried in code**, per the source doc's own instruction)
3. → add the independent NPL-increase slider's effect
4. → compute new provisions from the combined defaults
5. → apply interest-rate slider's effect on floating-rate loans/deposits (using `loans_by_rate_type`/
   `deposits_by_rate_type` from the snapshot — this is exactly why Notebook 6 needed the
   `PRODUCT_RATE_TYPE`/`ACCOUNT_RATE_TYPE` placeholder assumptions; **the same visible-assumption
   requirement applies here**)
6. → reduce capital by total losses, recompute RWA, recompute capital ratio
7. → separately recompute liquidity ratio from the deposit-outflow slider
   (`LCR = (HQLA − outflow) / net_outflows_30d`)

## 4. "Assumptions" Panel

A visible link/panel showing every hardcoded assumption feeding this screen's math — the
devaluation→default-uplift rule, the coverage ratio used for new provisions, `PRODUCT_RATE_TYPE`/
`ACCOUNT_RATE_TYPE`. Per the source doc: "bankers will ask what's behind the model, and being
able to show it immediately is the difference between a toy and a credible tool."

## 5. Acceptance Criteria

- [ ] Snapshot fetched exactly once per screen load, verified via network inspection during
      testing — zero additional backend calls on slider movement
- [ ] Waterfall chart correctly attributes impact across all 4 stress factors in the order from
      section 3
- [ ] Assumptions panel lists every hardcoded constant used in the calculation, not a partial list
- [ ] Not yet implemented

## 6. Non-Goals

- No server-side scenario computation (explicitly client-side, section 3)
- No real-time market data feeding the sliders (static snapshot per load, refreshed only on next
  page load — consistent with the rest of the pipeline's batch philosophy)
