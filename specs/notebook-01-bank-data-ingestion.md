# Spec: Notebook 1 — Bank Data Ingestion & Standardisation

**Status:** Implemented (not yet run against a live cluster)
**Supersedes:** the treasury-specific version of `notebooks/01_ingestion_standardisation.py`
(see "Relationship to prior work" below)
**Source of truth:** `Middle East bank data cleaning and reporting.md` (database schema section)
**File:** `notebooks/01_ingestion_standardisation.py`

---

## 1. Objective

Ingest the eight core banking tables described in the source doc from CSV into standardised
Delta tables, ready for Notebook 2's data-quality checks.

## 2. Relationship to Prior Work

The original Notebook 1 (see `specs/day-01-sample-data-and-notebook-scaffolding.md`, now
historical) ingested the three treasury-entity position CSVs (`lebanon_positions.csv`, etc.) per
`bank-x poc-brief.md`. Per an explicit decision to fully adopt the new source of truth, this
notebook has been **rewritten from scratch** for the bank-wide schema — treasury-specific logic
(entity-based FX conversion, `trade_id`/`currency_pair` handling) has been removed from this file
entirely. The treasury CSVs and the old spec remain in the repo as historical reference but are no
longer consumed by any notebook. See `CLAUDE.md` for the current state of that relationship.

## 3. Scope

**In scope:** reading, type-standardising, and writing to Delta the eight tables: `customers`,
`accounts`, `loans`, `transactions`, `branches`, `capital_positions`, `liquidity_daily`, `fx_rates`.

**Out of scope:**
- Data-quality checks (Notebook 2)
- Currency conversion to a single reporting currency (deferred to the application layer /
  calculation stage — this notebook standardises types only, doesn't convert amounts)
- Nightly precomputed summary tables (e.g. `branch_performance_monthly`) — those belong to the
  application layer per `PLATFORM-BUILD-PLAN.md`, not this ingestion notebook

## 4. Input

Eight CSVs, one per table, read from a configurable `input_dir` widget (default
`/Volumes/bank_poc/raw`, mirroring the original notebook's pattern). Sample files exist at
`bank-data/*.csv` in this repo — see section 7 for what's deliberately wrong in them.

## 5. Requirements

- Each table's date columns are standardised to `YYYY-MM-DD` (tries `YYYY-MM-DD` then
  `DD/MM/YYYY`, same coalesce pattern as the original treasury notebook, in case different core
  systems export different formats)
- Each table's numeric columns are cast via `try_cast` to `double` — malformed values become
  null here, not an ingestion error; Notebook 2 is what flags the null
- `accounts.currency`, `loans.currency`, `transactions.currency` are uppercased/trimmed (not
  validated against a known-currency list — that's Notebook 2)
- `fx_rates.currency_pair` gets the same `XXX/YYY` slash-insertion normalisation as the original
  treasury notebook (reused logic, same rationale: fixes clean 6-letter codes, leaves genuinely
  malformed ones for Notebook 2)
- `capital_positions.month` (a `YYYY-MM` string, not a full date) is trimmed only; format
  validation is Notebook 2's job
- Nothing is dropped or defaulted at this stage — malformed/missing values become null and flow
  downstream, consistent with the original notebook's "don't silently discard" principle
- Output: eight Delta tables, prefixed `raw_` (`raw_customers`, `raw_accounts`, `raw_loans`,
  `raw_transactions`, `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`, `raw_fx_rates`)

## 6. Acceptance Criteria

- [x] All eight source CSVs are read and each produces exactly one `raw_*` Delta table
- [x] Malformed numeric values (e.g. a blank `amount` in `transactions.csv`) become null, not a
      row-drop or a notebook error
- [x] `fx_rates.csv`'s already-slashed pairs (`USD/LBP`, etc.) pass through unchanged; no
      no-slash pairs exist in the current sample data, so slash-insertion is logic-verified but
      not exercised by the current sample — worth adding a no-slash row if this needs demoing
      explicitly
- [ ] **Not yet verified**: execution against a live Databricks cluster

## 7. Sample Data Summary (`bank-data/*.csv`)

Small, hand-traceable datasets (6-10 rows/table) with deliberately injected issues for Notebook
2 to catch — see `specs/notebook-02-bank-data-quality.md` section 7 for the full traceability
table. Referential integrity between tables is mostly consistent (e.g. `accounts.customer_id`
values mostly exist in `customers.csv`) except where an orphan is deliberately injected.

**Assumption flagged:** this sample data was generated for notebook-testing purposes, not
requested explicitly with the same rigor as the original treasury brief's section 4. Row counts
are intentionally small and demo-scannable, not a stand-in for the "two million transactions"
scale the source doc mentions for performance-proofing (see `PLATFORM-BUILD-PLAN.md` open
decisions) — confirm before assuming this dataset is sufficient for anything beyond notebook
logic verification.

## 8. Non-Goals

- No FX conversion to reporting currency
- No synthetic data generation beyond what's needed to exercise Notebook 2's checks
- No live cluster run (blocked on Databricks environment setup, same as before)
