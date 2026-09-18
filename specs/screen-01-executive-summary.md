# Spec: Screen 1 — Executive Summary

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` Track C, Per-Screen Shallow Scope
**Depends on:** `specs/notebook-03-kpi-summary.md` (data), `specs/fastapi-backend.md` section 2.1

---

## 1. Objective

The board's 2-minute morning check per the source doc: 8 KPI tiles, a trend chart, a
plain-language alert strip.

## 2. Layout

- **Top strip**: bank name, current date, "data as of [timestamp]" — the timestamp matters (per
  source doc: a CEO needs to know if they're looking at last night's numbers or last week's)
- **8 tiles, 4×2 grid**: measure name (small), value (large/bold), change-since-last-period with
  arrow, coloured bar (green/amber/red) along the bottom
- **Trend chart**: below the tiles — **single data point for this POC**, not the source doc's
  24-month line (no historical `kpi_daily_summary` accumulation exists yet — see
  `3-WEEK-POC-PLAN.md`'s shallow scope). Render it honestly (a single dot, or a note that history
  accumulates daily going forward), don't fake historical points.
- **Alert strip**: 3-5 plain-language sentences, threshold-generated from the 8 KPI values against
  the red/amber cutoffs (a small settings table per KPI, per the source doc)

## 3. The 3 Assumption-Based Tiles — Required UI Treatment

`nim_pct`, `cost_to_income_pct`, `roe_pct` come from `kpi_daily_summary` with
`assumptions_applied` populated (`specs/notebook-03-kpi-summary.md` section 7). **These three
tiles must show a visible marker (e.g. a small ⓘ icon) linking to a tooltip naming the specific
assumption** (`DEPOSIT_RATE_BY_TYPE`, `REGION_CURRENCY`, or tier1-as-equity) — per
`3-WEEK-POC-PLAN.md`'s explicit requirement that these "need a UI footnote wherever they feed a
number." Do not render them identically to the 5 directly-computed tiles.

## 4. Interactions

- Click a tile → navigates to the relevant detail screen (e.g. NPL tile → Screen 2, filtered)
- Click an alert strip line → navigates to the relevant filtered detail view
- One filter, top right: date selector (limited utility until multi-day history exists, but build
  the control now so it's ready)

## 5. Acceptance Criteria

- [ ] All 8 tiles render, with the 3 assumption-based ones visibly marked per section 3
- [ ] Page loads without any live aggregation — purely reads `GET /api/v1/kpi-summary/latest`
- [ ] Alert strip text is generated from actual KPI values against real thresholds, not hardcoded
      demo strings
- [ ] Not yet implemented

## 6. Non-Goals

- No 24-month trend (section 2) until real history accumulates
- No per-country/per-entity breakdown on this screen (that's Screen 2/5's job)
