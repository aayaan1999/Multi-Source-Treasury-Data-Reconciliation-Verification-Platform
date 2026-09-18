# Spec: Screen 3 — Regulatory Reporting

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` Track C, Per-Screen Shallow Scope (**one report template
only** — Capital Adequacy, the one the source doc works out in full)
**Depends on:** `specs/fastapi-backend.md` section 2.3, `specs/postgres-schema.md` section 2.4
(`report_instances`, `report_line_items`, `calculation_audit`, `validation_rules`)

---

## 1. Objective

Not a dashboard — a filing tool. Produce an exact document, prove where every figure came from,
track submission status. The source doc is explicit that this screen is judged on correctness and
export quality, not visual polish.

## 2. Sections

1. **Report calendar**: table of `report_instances` — name/frequency/period/due date/status,
   coloured by urgency (red < 5 days unsubmitted, amber < 10, green submitted). **For this POC,
   seed a handful of example rows rather than building a general scheduling engine** — the
   report-calendar logic (recurring due dates, frequency rules) is out of scope; only the Capital
   Adequacy template's actual line items and export are real
2. **Open report view**: the Capital Adequacy return laid out exactly as the source doc's worked
   example (Section A Capital, Section B RWA, Section C Ratios — same line codes: A.1-A.9,
   B.1-B.4, C.1-C.4)
3. **Drill-to-source**: click any line → `GET /api/v1/reports/{id}/drill/{line_code}` → panel
   showing formula text, source table(s), record count, calculated-at timestamp — **this is the
   single feature the source doc calls out as mattering most to bankers/auditors.** Every line in
   the Capital Adequacy template must have a real `calculation_audit` entry, not a placeholder
4. **Validation checks**: 2-3 real checks for this POC (not the full `validation_rules` engine) —
   arithmetic consistency (Tier 1 + Tier 2 = Total Capital), required-fields-present. Green
   passes, red blocks submission
5. **Comparison with prior period**: this period vs. last vs. % change — **limited by the same
   single-snapshot data constraint as Screen 1/2** — show it as a 2-column table (current period,
   "N/A — no prior period yet") rather than fabricating a comparison
6. **Export**: PDF (ReportLab) and Excel (openpyxl), for the Capital Adequacy template only.
   **Test both thoroughly** — the source doc explicitly calls a broken export button a deal-loser

## 3. Acceptance Criteria

- [ ] Every line in the rendered Capital Adequacy report drills to a real `calculation_audit`
      entry, not a stub
- [ ] PDF export matches the source doc's line-item layout (Section A/B/C, line codes)
- [ ] Excel export opens cleanly and contains the same figures as the PDF (no drift between the
      two export paths)
- [ ] Not yet implemented

## 4. Non-Goals

- No report types beyond Capital Adequacy (Liquidity Coverage, Credit Classification, etc. — all
  named in the source doc's example table but not built)
- No general-purpose report-scheduling engine (section 2 item 1)
- No real prior-period comparison (section 2 item 5)
