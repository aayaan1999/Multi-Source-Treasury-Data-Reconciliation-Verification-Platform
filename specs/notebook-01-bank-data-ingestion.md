# Spec: Notebook 1 — Bank Data Ingestion & Standardisation

**Status:** Implemented; ran to completion without errors on Azure Databricks (2026-09-21). Output values not yet compared against this spec's traceability table.
**Supersedes:** the treasury-specific version of `notebooks/01_ingestion_standardisation.py`
(see "Relationship to prior work" below)
**Source of truth:** `Middle East bank data cleaning and reporting.md` (database schema section)
**File:** `notebooks/01_ingestion_standardisation.py`
**Source tags (2026-09-24):** every `raw_*` row now also carries `source_system`, `source_country`,
`ingest_batch_id` and `source_file`, with two new parameters (`source_system`, `source_country`) —
see `specs/source-tagging.md`. Not yet run on a cluster.

---

## 1. Objective

Ingest the eight core banking tables described in the source doc from CSV into standardised
Delta tables, ready for Notebook 2's data-quality checks. In medallion terms, this notebook
produces the **Bronze layer**: the `raw_*` Delta tables have standardised types/formats but are
not yet validated (no structural or referential checks — that's Notebook 2's Silver layer). The
landing-zone files this notebook reads from `input_dir` are Bronze too, in the sense used by
`specs/multi-source-ingestion-adf.md` — Bronze spans both "files landing in `input_dir`" and "the
`raw_*` tables this notebook writes from them."

**Update:** per `specs/multi-source-ingestion-adf.md`, Bronze-layer files landing in
`input_dir` may now originate from an Azure Data Factory-orchestrated pipeline (database pulls,
API extracts) rather than only manual CSV uploads. **This notebook requires zero code changes for
that** — it reads whatever's in `input_dir` regardless of upstream origin, by design (see that
spec's section 2, "two layers, not one"). If a future change to this notebook is ever motivated by
"we added a new source system," that's a sign the source-agnostic design has broken down and
should be reconsidered, not accepted as normal.

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
`/Volumes/dbw_bankx_treasury_poc/raw/raw/resources` — a full `/Volumes/<catalog>/<schema>/<volume>/<folder>` path;
omitting the volume segment fails with `UC_VOLUME_NOT_FOUND`). Sample files exist at
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
- [x] Executed against a live Databricks cluster: ran to completion with no errors (2026-09-21). Input path is now
      `/Volumes/dbw_bankx_treasury_poc/raw/raw/resources`. Row counts/nulls not yet checked against section 7

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
- No live cluster run at original spec time (since done — see section 6)
