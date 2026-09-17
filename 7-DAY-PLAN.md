# Original 7-Day Plan (Databricks portion only — superseded beyond Day 3)

**This plan is superseded by `PLATFORM-BUILD-PLAN.md`** for everything past the Databricks data
layer. It's kept here because Days 1-3 (sample data + Notebooks 1-4) are still accurate — the
Databricks scope didn't change when the product vision expanded to the full 6-screen platform in
`Middle East bank data cleaning and reporting.md`. Days 4-7 below described building the original
Appian workflow, which no longer applies; see `PLATFORM-BUILD-PLAN.md` Phases 1-6 instead.

Based on the POC scope in `bank-x poc-brief.md` section 5.

---

## Day 1 — Sample Data + Notebook Scaffolding
**Owner: Dev Lead + Claude Code**

- [x] Dev Lead builds three sample CSVs with deliberately injected issues:
  - `lebanon_positions.csv` — USD, `YYYY-MM-DD` dates
  - `ksa_positions.csv` — SAR, `DD/MM/YYYY` dates, `USDSAR`-style pairs
  - `qatar_positions.csv` — QAR, renamed columns (e.g. `trade_amt`), duplicate trade IDs
  - Inject: 3-5 missing values/file, 2-3 format mismatches, 1-2 limit breaches, 1 duplicate record, 1 cross-entity mismatch (same trade_id, different amount, across two files)
- [x] Claude Code generates the PySpark notebooks (Notebooks 1-2 done; 3-4 pending):
  - Notebook 1: Ingestion & Standardisation
  - Notebook 2: Data Quality Verification
  - Notebook 3: Reconciliation & Consolidated Report
  - Notebook 4: Exception Summary Report
- [ ] Confirm Databricks environment answers (brief section 11): runtime version, Delta Lake availability, FX rate table values to hardcode

**End of day:** Sample CSVs committed to repo; 4 notebook files exist and are structurally complete.

---

## Day 2 — Notebook Review & First Run
**Owner: Databricks Developer**

- [ ] Review Notebook 1 & 2 logic against actual Databricks cluster config
- [ ] Adjust schema standardisation for real column-naming quirks in sample data
- [ ] Run Notebook 1 against sample CSVs → validate `treasury_positions_raw`
- [ ] Run Notebook 2 → validate `treasury_positions_clean` and `treasury_positions_exceptions`
- [ ] Confirm every injected data-quality issue produced the correct flag label

**End of day:** Notebooks 1-2 run successfully; exceptions table contains all 8 flag types correctly.

---

## Day 3 — Reconciliation, Summary, and Output Validation
**Owner: Databricks Developer**

- [ ] Run Notebook 3 → validate `treasury_consolidated_report` (group exposure by currency pair, limit breach flags)
- [ ] Run Notebook 4 → validate `exception_summary` (counts by type/entity)
- [ ] Export both to CSV for the application layer to import
- [ ] Fix any data issues found in end-to-end run
- [ ] Freeze the CSV export format/schema — this is the contract the PostgreSQL import job (`PLATFORM-BUILD-PLAN.md` Phase 1) will build against

**End of day:** All 4 output Delta tables validated; CSV exports ready and schema-frozen.

---

## What comes next

Continue with `PLATFORM-BUILD-PLAN.md` Phase 1 (Foundation) onward.
