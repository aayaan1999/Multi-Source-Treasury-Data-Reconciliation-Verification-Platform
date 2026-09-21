# Spec: Screen 1 — Executive Summary

**Status:** Built in `frontend/` (React + Vite + Tailwind + Recharts). 32 tests pass; checked in a real browser
against the real API on a throwaway Postgres with 6 days of seeded KPI rows (dark and light themes, single-day and
multi-day views, assumption tooltip). **Not yet run against the deployed pipeline's data in Neon.** Not verified at a
real phone-width viewport.
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

## 4a. What was built, and where it departs from the sections above

- **Trend = four small panels, not one chart.** CAR, LCR, NPL and dollarization each get their own panel with their own
  scale, because ratios on different scales can't share an axis (no dual-axis charts). Each panel's regulatory/internal
  limit is a dashed line in the plot, explained by a caption under the title (an in-plot label collided with the data
  line). With one day of history each panel is a single dot and a note says so; a "Show as table" toggle lists every
  value.
- **Thresholds are demo placeholders** in `frontend/src/kpi/kpiConfig.js` (the source document says red/amber limits live
  in an adjustable settings table but gives no numbers, and no such table exists). Anchors: CAR minimum 12%, NPL limit
  5% (the Screen 6 example), cost-to-income 60%, LCR 100%. Total assets has no limit ("No limit set"). Move these into a
  settings table and confirm them with the source-document owner. A footnote on the page says so.
- **Change since last period** is versus the previous day's row (the pipeline is daily), in percentage points for ratios
  and relative % for total assets, with an arrow and a "better/worse" label for screen readers.
- **"Data as of"** shows the date only (the API stores `calculation_date`, not a timestamp) and the alert strip adds a
  "N days old" line when the newest data is 2+ days old (not when the user chose an older date on purpose).
- **Date selector** lists the dates that exist; picking one re-renders tiles, trend and alerts from that day's row.
- **Assumption tiles** (NIM, cost-to-income, ROE) carry a labelled "Assumption" button that opens a tooltip naming the
  specific `assumptions_applied` entries for that KPI.
- **Login** is a simple demo sign-in (token in `localStorage`); a 401 from the API signs the user out.
- **Tile and alert-line clicks** go to placeholder pages for Screens 2, 4 and 5 (not built) that show the requested filter.

## 4b. Running it

```
cd frontend
npm install
npm run dev        # http://localhost:5173 ; /api is proxied to the backend at http://127.0.0.1:8000
npm test
```
The project folder name contains an `&`, which breaks the `.cmd` shims that `npx vite` and `node_modules\.bin\*` use on
Windows, so the npm scripts call `node node_modules/...` directly. Always use `npm run ...`, never `npx vite`. The
backend must be running (see `specs/fastapi-backend.md` section 4a) and seeded with demo users.

## 5. Acceptance Criteria

- [x] All 8 tiles render, with the 3 assumption-based ones visibly marked per section 3 (tested; seen in the browser)
- [x] Page loads without any live aggregation — reads `GET /api/v1/kpi-summary/latest` plus `/history` for the trend,
      the change arrows and the date selector; nothing is computed server-side per request
- [x] Alert strip text is generated from actual KPI values against the configured thresholds, not hardcoded strings
      (tested: the wording changes with the numbers). [ ] Thresholds themselves are placeholders pending confirmation
- [ ] Verified with the real pipeline data in Neon
- [ ] Verified at a real phone-width viewport

## 6. Non-Goals

- No 24-month trend (section 2) until real history accumulates
- No per-country/per-entity breakdown on this screen (that's Screen 2/5's job)
