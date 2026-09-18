# Spec: Screen 2 — Portfolio & Credit Risk

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` Track C, Per-Screen Shallow Scope
**Depends on:** `specs/notebook-06-portfolio-branch-scenario-snapshot.md` (all data for this
screen), `specs/fastapi-backend.md` section 2.2

---

## 1. Objective

Where the Chief Risk Officer finds *what and where* risk is concentrated, per the source doc.

## 2. Sections (each backed by one Notebook 6 output table — see that spec for exact formulas)

1. **Top strip, 5 boxes**: Gross Loans, NPL Amount, NPL Ratio, Coverage Ratio, Cost of Risk —
   derived from `loan_stage_summary`
2. **Loan book sliced 4 ways** (product/segment/branch/currency), each chart showing **two bars
   per category — total and bad-loan** (source doc's explicit design point: totals alone hide
   what the screen exists to reveal) — from `loan_breakdown_by_dimension`
3. **Bad-loan trend**: **cut for this POC** (needs 24 months of history this data doesn't have)
   — show current NPL ratio as a static reference line instead of a trend, and say so in the UI
4. **IFRS 9 staging table**: stage / count / outstanding / provisions / coverage% — from
   `loan_stage_summary`. Stage-migration chart ("loans moving Stage 1→2") also cut, same reason
   as item 3
5. **Top-20 exposures**: from `top_exposures`, with `pct_of_capital`, red-highlighted if it
   breaches a configurable single-borrower limit
6. **Ageing table**: from `loan_ageing_summary`
7. **LTV distribution**: from `ltv_distribution`, with the 0-collateral-as-`>100%` bucketing
   already defined in that spec — don't re-derive the bucket logic in the frontend

## 3. Interactions

- One filter bar (date/product/segment/branch/currency) — every chart responds together
- Every chart/table row drills down to the underlying loan list (`GET /api/v1/portfolio/loans`)
- Excel export button (risk teams live in Excel, per source doc)

## 4. Acceptance Criteria

- [ ] Every chart shows total + bad-loan bars, not totals alone (section 2 item 2)
- [ ] LTV bucket for a 0-collateral loan renders in `>100%`, not as an error or omitted row
- [ ] Cut items (trend line, stage migration) are visibly absent with an honest note, not silently
      missing without explanation
- [ ] Not yet implemented

## 5. Non-Goals

- 24-month trend / stage-migration chart (section 2 items 3-4)
- Customer-level fraud/behavioral flags on this screen (that's Screen 6's job via the exception
  workflow, not embedded here)
