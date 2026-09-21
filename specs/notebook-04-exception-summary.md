# Spec: Notebook 4 — Exception Summary Report

**Status:** Implemented; ran to completion without errors on Azure Databricks (2026-09-21). Output values not yet compared against this spec's traceability table.
**Supersedes:** the treasury-specific "Exception Summary Report" design (counts by entity/flag
type against `treasury_positions_exceptions`) — rebuilt against Notebook 2's `data_quality_exceptions`
log instead
**Source of truth:** `Middle East bank data cleaning and reporting.md`
**File (planned):** `notebooks/04_exception_summary.py`
**Depends on:** `specs/notebook-02-bank-data-quality.md` (reads `data_quality_exceptions` and the
8 `raw_*` tables)

---

## 1. Objective

Summarise Notebook 2's `data_quality_exceptions` log into small, demo-ready aggregate tables:
which source table has the most data-quality issues, of what type, and what fraction of each
table's rows are affected. This is the notebook-layer equivalent of what Screen 6's "breach
alerts" and a compliance officer's morning triage would want to see at a glance, and it's simple
by design — unlike Notebook 3, there's no schema gap or currency-conversion question here, since
counting rows doesn't require summing monetary amounts.

## 2. Scope

**In scope:** two small summary tables built entirely from `data_quality_exceptions` plus row
counts from the 8 `raw_*` tables (for the exception-rate denominator).

**Out of scope:**
- Any write-back into Screen 6's `tasks`/`breaches` tables — this notebook only summarises for
  reporting; task creation from a breach is application-layer logic per `PLATFORM-BUILD-PLAN.md`
  Phase 1 ("`limits` table + a nightly breach-check job")
- Trend-over-time ("exceptions rising for 6 consecutive months") — this notebook computes today's
  snapshot only, same reasoning as Notebook 3's non-goals

## 3. Output Tables

### `exception_summary_by_flag`

One row per `(source_table, flag_label)` combination that occurs at least once:

| Column | Type | Notes |
|---|---|---|
| `calculation_date` | date | |
| `source_table` | string | |
| `flag_label` | string | |
| `exception_count` | long | `COUNT(*)` from `data_quality_exceptions` grouped by these two columns |

### `exception_summary_by_table`

One row per source table, including tables with zero exceptions (so a clean table shows `0`, not
an absence):

| Column | Type | Notes |
|---|---|---|
| `calculation_date` | date | |
| `source_table` | string | |
| `raw_row_count` | long | `COUNT(*)` from the corresponding `raw_*` table |
| `flagged_record_count` | long | `COUNT(DISTINCT record_key)` from `data_quality_exceptions` for this table — a record with 2 flags still counts once here |
| `exception_rate_pct` | double | `flagged_record_count / raw_row_count × 100` |

`exception_rate_pct` is the number that answers "which entity/table has the most data quality
issues" directly, without a human eyeballing raw counts against differently-sized tables.

## 4. Design Decisions

- `flagged_record_count` uses `DISTINCT record_key`, not total exception rows, so a record with
  multiple flags (possible per Notebook 2's design) isn't double-counted as if it were two bad
  records
- `exception_summary_by_table` is a `LEFT JOIN` from the 8-table list against
  `data_quality_exceptions`, not an `INNER JOIN` — a table with zero exceptions must still appear
  with `flagged_record_count = 0`, not be silently missing from the output

## 5. Acceptance Criteria

- [x] Written: `notebooks/04_exception_summary.py`. **Ran to completion with no errors on Azure Databricks (2026-09-21, reported by the project owner); output values not yet compared against the traceability table**; the checks below remain unverified.
- [ ] `exception_summary_by_table` has exactly 8 rows (one per source table) every run, regardless
      of whether a table has any exceptions
- [ ] `exception_summary_by_flag` row counts match `data_quality_exceptions` grouped counts exactly
- [ ] Sum of `exception_count` in `exception_summary_by_flag` for a given `source_table` equals
      the number of exception log rows for that table (not necessarily `flagged_record_count`,
      since one record can contribute multiple flag rows)
- [ ] Values match the hand-traced table in section 6 when run against `bank-data/*.csv`

## 6. Traceability (hand-computed against `bank-data/*.csv`, per `specs/notebook-02-bank-data-quality.md` section 7)

`exception_summary_by_table`:

| source_table | raw_row_count | flagged_record_count | exception_rate_pct |
|---|---|---|---|
| customers | 10 | 3 (`C004`, `C009`, `C010`) | 30.0% |
| accounts | 10 | 3 (`ACC004`, `ACC009`, `ACC010`) | 30.0% |
| loans | 10 | 5 (`L004`, `L006`, `L008`, `L009`, `L010`) | 50.0% |
| transactions | 10 | 3 (`T0008`, `T0009`, `T0010`) | 30.0% |
| branches | 6 | 1 (`B06`) | 16.7% |
| capital_positions | 6 | 2 (blank-month row, `2026-08`) | 33.3% |
| liquidity_daily | 8 | 2 (blank-date row, `2026-09-13`) | 25.0% |
| fx_rates | 10 | 3 (both `2026-09-16 USD/SAR` rows, `2026-09-17 USD/QAR`) | 30.0% |

**`loans` has both the highest count and highest rate of any table (50%)** — the clearest "which
table has the most issues" story for a demo, and it lines up naturally with the source doc's own
emphasis on loan-book quality (IFRS 9 staging, NPL tracking).

`exception_summary_by_flag`: 22 total rows expected, one per flag listed in
`specs/notebook-02-bank-data-quality.md` section 7 (no record in the current sample data trips
more than one check, so `exception_count` is 1 for every `(source_table, flag_label)` pair in
this particular dataset — that will change once a richer sample or real data is used).

These are hand-computed, not verified by an actual run — treat as the test plan to check against
real notebook output once implemented and run on a live cluster.

## 7. Non-Goals

- No severity ranking (block/warn/info) — that's `validation_rules` in the application layer, not
  this notebook, consistent with Notebook 2's own non-goals
- No natural-language alert text ("Bad loans in SME lending have risen...") — presentation logic,
  application layer
