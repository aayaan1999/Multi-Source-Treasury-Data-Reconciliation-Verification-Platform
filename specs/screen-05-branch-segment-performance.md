# Spec: Screen 5 — Branch & Segment Performance

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` Track C, Per-Screen Shallow Scope
**Depends on:** `specs/notebook-06-portfolio-branch-scenario-snapshot.md` (all data),
`specs/fastapi-backend.md` section 2.5

---

## 1. Objective

Who's making the bank money and who's losing it — per the source doc, the question most banks
genuinely don't know the answer to because costs and revenue sit in different systems.

## 2. Sections

1. **Top strip, 4 boxes**: Total Revenue, Total Cost, Profit, Branches in Loss (count where
   `profit_usd < 0`) — from `branch_performance_summary`
2. **Branch league table**: every branch, sorted worst-to-best by profit, columns per the source
   doc (deposits/loans/revenue/cost/profit/cost-to-income/staff/profit-per-staff), **red row
   where profit is negative**. From `branch_performance_summary` — **note in the UI wherever
   `REGION_CURRENCY` assumption affected the cost figure** (same "surface the assumption"
   principle as Screen 1's tiles)
3. **Regional rollup**: `GROUP BY region` on the same table, bar chart revenue vs. cost per
   region — computed client-side or via a small aggregation query, not a separate notebook output
4. **Segment performance**: from `segment_performance_summary` — **the `profit_usd` column here
   is pro-rated via `SEGMENT_COST_ALLOCATION`, not measured** (`specs/notebook-06-...md` section
   3) — **this needs the same visible-assumption UI treatment**, arguably more prominently than
   the others, since "Profit" without qualification implies precision the number doesn't have.
   Consider labeling the column "Profit (cost allocated proportionally)" rather than just "Profit"
5. **Product performance**: from `product_performance_summary` — `net_contribution_usd` is
   directly computable (no assumption involved, per that spec), can be presented without a
   footnote
6. **Channel usage**: from `transactions`, grouped by `channel` — **"now" only, no 12-months-ago
   comparison** (no historical data, per `3-WEEK-POC-PLAN.md`'s shallow scope)
7. **Efficiency quadrant scatter**: revenue (x) vs. cost-to-income (y), dot size = deposits, one
   dot per branch, from the same `branch_performance_summary` data as item 2 — no new backend
   query needed

## 3. Interactions

- One filter bar (period/region/segment/product/currency)
- Every row drills to that branch/segment's customers and loans
- Excel export

## 4. Acceptance Criteria

- [ ] Branch league table correctly reds out negative-profit rows
- [ ] Segment "Profit" column is visibly labeled as allocated, not measured (section 2 item 4)
- [ ] Channel usage shows current period only, with no fabricated "12 months ago" comparison
- [ ] Not yet implemented

## 5. Non-Goals

- No true cost allocation methodology beyond `SEGMENT_COST_ALLOCATION`'s proportional split — the
  source doc itself says direct-branch-opex-only is the honest POC scope, full allocation would
  be "configured with your finance team" in a real engagement
- No 12-month channel-mix comparison (section 2 item 6)
