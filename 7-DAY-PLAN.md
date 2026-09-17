# 7-Day Build Plan: Multi-Source Treasury Data Reconciliation & Verification Platform

Based on the POC scope in `bank-x poc-brief.md`. Target: working demo for Bank x within 1 week.

---

## Day 1 — Sample Data + Notebook Scaffolding
**Owner: Dev Lead + Claude Code**

- [ ] Dev Lead builds three sample CSVs with deliberately injected issues:
  - `lebanon_positions.csv` — USD, `YYYY-MM-DD` dates
  - `ksa_positions.csv` — SAR, `DD/MM/YYYY` dates, `USDSAR`-style pairs
  - `qatar_positions.csv` — QAR, renamed columns (e.g. `trade_amt`), duplicate trade IDs
  - Inject: 3-5 missing values/file, 2-3 format mismatches, 1-2 limit breaches, 1 duplicate record, 1 cross-entity mismatch (same trade_id, different amount, across two files)
- [ ] Claude Code generates all 4 PySpark notebook templates (structure + logic, not yet run against real cluster):
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
- [ ] Export both to CSV for Appian consumption
- [ ] Fix any data issues found in end-to-end run
- [ ] Freeze the CSV export format/schema — this is the contract Appian will build against

**End of day:** All 4 output Delta tables validated; CSV exports ready and schema-frozen for Appian.

---

## Day 4 — Appian: Exception Queue + Case Detail
**Owner: Appian Developer**

- [ ] Import/connect `treasury_positions_exceptions` CSV (file drop or connected system, per brief section 11 answer)
- [ ] Build **Exception Queue** view: entity, trade date, currency pair, flag type, description, amount; claim-a-case action
- [ ] Build **Case Detail** view: full record detail, Approve/Reject/Request-info actions, mandatory comment field
- [ ] Log every action with timestamp + user ID

**End of day:** Officer can browse exceptions, open a case, and take an action with a comment.

---

## Day 5 — Appian: Consolidated Report + Audit Trail
**Owner: Appian Developer**

- [ ] Build **Consolidated Report** view from `treasury_consolidated_report` CSV; highlight limit breaches in red; add Export-to-PDF button
- [ ] Build **Audit Trail** view: every case action (user, timestamp, action, comment), filterable by date/entity/user/action type

**End of day:** All 4 Appian views functional against static/sample exports.

---

## Day 6 — Integration & End-to-End Test
**Owner: Both**

- [ ] Wire Databricks CSV exports into Appian's ingestion point (file drop or connected system)
- [ ] Run the full pipeline once, start to finish: raw CSVs → notebooks → exceptions in Appian → officer resolves a case → consolidated report reflects resolution → audit trail shows the action
- [ ] Fix any breaks in the handoff (schema drift, encoding, date format mismatches between Databricks output and Appian input)

**End of day:** One clean end-to-end run completes without manual intervention.

---

## Day 7 — Demo Rehearsal & Polish
**Owner: Dev Lead**

- [ ] Rehearse the demo flow (brief section 9):
  1. Show the three raw entity files with visible data issues
  2. Run/show Notebook 1 output — unified schema
  3. Run/show Notebook 2 output — exceptions flagged automatically
  4. Appian: officer claims a case, reviews, approves/rejects with a comment
  5. Consolidated Report view — group exposure across entities
  6. Audit Trail — full history for a record
- [ ] Fix any rough edges (UI polish, timing, talking points)
- [ ] Prepare and freeze the demo environment (no live edits day-of)

**End of day:** Demo-ready environment; dry run completed with the key message landed — *"the system finds inconsistencies automatically, routes them for human decision, and keeps the audit trail without anyone reconstructing it."*

---

## Critical Path Notes

- Day 3's schema freeze is the hard dependency for Days 4-5 — Appian work can't meaningfully start until the CSV contract is fixed.
- If Databricks environment questions (brief section 11) aren't answered before Day 1, that blocks everything — resolve those first.
- Days 2-3 (Databricks) and Days 4-5 (Appian) could overlap if Appian starts against mocked/sample exports early and re-points to real Databricks output once frozen — worth considering if the 1-week timeline is tight.
