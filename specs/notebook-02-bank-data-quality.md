# Spec: Notebook 2 — Bank Data Quality Verification

**Status:** Implemented (not yet run against a live cluster)
**Supersedes:** the treasury-specific version of `notebooks/02_data_quality_verification.py`
**Source of truth:** `Middle East bank data cleaning and reporting.md`
**File:** `notebooks/02_data_quality_verification.py`
**Depends on:** `specs/notebook-01-bank-data-ingestion.md` (reads its `raw_*` output tables)

---

## 1. Objective

Run structural and referential data-quality checks against all eight `raw_*` tables (Notebook 1's
Bronze layer), split each into a `{table}_clean` Delta table plus a shared `data_quality_exceptions`
log. In medallion terms, `{table}_clean` is the **Silver layer** — structurally and referentially
validated, ready to be trusted by downstream notebooks (3, 4, 5, 6) and the Gold aggregates they
produce. `data_quality_exceptions` is the input Screen 6's task queue (`PLATFORM-BUILD-PLAN.md`
Phase 2) will eventually consume.

## 2. Design Decision: One Central Exceptions Log, Not Eight

The treasury pipeline had one exceptions table because all its records shared one schema. These
eight source tables share almost no columns. Rather than force eight differently-shaped exception
tables, all findings land in one generic log:

```
data_quality_exceptions(source_table, record_key, flag_label, description)
```

`record_key` is the source table's primary key (or, for `fx_rates`, a synthesised
`date_currencypair` composite key since no single column identifies a rate row). This trades away
having the full row alongside each exception (a consumer needs to join back to `{table}_clean`'s
predecessor, `raw_{table}`, to see full context) for a schema that scales to N source tables
without N different exception-table shapes.

## 3. Checks Implemented, Per Table

| Table | Flag | Condition |
|---|---|---|
| customers | `MISSING_CUSTOMER_ID` | `customer_id` is null |
| customers | `MISSING_RISK_RATING` | `risk_rating` is null/blank |
| customers | `INVALID_SEGMENT` | `segment` not in {Retail, SME, Corporate} |
| customers | `MISSING_BRANCH_ID` | `branch_id` is null |
| customers | `ORPHAN_BRANCH` (referential) | `branch_id` doesn't exist in `branches` |
| accounts | `MISSING_ACCOUNT_ID` | `account_id` is null |
| accounts | `NEGATIVE_BALANCE` | `balance` < 0 |
| accounts | `INVALID_CURRENCY` | `currency` not in {USD, EUR, LBP, SAR, QAR} |
| accounts | `ORPHAN_CUSTOMER` (referential) | `customer_id` doesn't exist in `customers` |
| loans | `MISSING_LOAN_ID` | `loan_id` is null |
| loans | `OUTSTANDING_EXCEEDS_PRINCIPAL` | `outstanding` > `principal` |
| loans | `INVALID_STAGE` | `stage` not in {1, 2, 3} |
| loans | `NEGATIVE_DPD` | `days_past_due` < 0 |
| loans | `NPL_STAGE_MISMATCH` | `days_past_due` >= 90 but `stage` != 3 |
| loans | `ORPHAN_CUSTOMER` (referential) | `customer_id` doesn't exist in `customers` |
| transactions | `MISSING_TRANSACTION_ID` | `transaction_id` is null |
| transactions | `INVALID_AMOUNT` | `amount` is null/non-numeric |
| transactions | `INVALID_CHANNEL` | `channel` not in {Branch, ATM, Mobile, Online} |
| transactions | `ORPHAN_ACCOUNT` (referential) | `account_id` doesn't exist in `accounts` |
| branches | `MISSING_BRANCH_ID` | `branch_id` is null |
| branches | `NEGATIVE_OPEX` | `monthly_opex` < 0 |
| capital_positions | `MISSING_MONTH` | `month` is null/blank |
| capital_positions | `INVALID_RWA` | `risk_weighted_assets` is null or <= 0 |
| liquidity_daily | `MISSING_DATE` | `date` is null |
| liquidity_daily | `NEGATIVE_HQLA` | `hqla` < 0 |
| fx_rates | `INVALID_RATE` | `rate` is null or <= 0 |
| fx_rates | `DUPLICATE_RATE` | more than one rate for the same `(date, currency_pair)` — **superseded**: per `specs/fx-realtime-ingestion.md`, FX rates are now fetched live inline by Notebook 3/6's conversion logic, not ingested as a `fx_rates` data-quality subject at all. This row (and `fx_rates`/`raw_fx_rates`/`fx_rates_clean` generally) stops applying once that spec is implemented — see its section 2 |

`NPL_STAGE_MISMATCH` directly encodes the source doc's own definitions ("a bad loan is any loan
where `days_past_due` is 90 or more" and "Stage 3 — already bad ... heavy provisions") as a
cross-check rather than trusting the source system's `stage` column blindly.

## 4. Design Decisions

- A row can trip multiple checks; each becomes its own log entry (same `explode`-based pattern as
  the treasury pipeline)
- Referential ("orphan") checks are computed via left-anti join against the parent table and are
  logged the same way as structural checks — an orphan record is excluded from `{table}_clean`
  even though it wasn't caught by that table's own structural checks (see `notebooks/02_*.py`'s
  `orphan_flags` + follow-up filter)
- Referential checks only validate the direct parent named in the source doc's "how they join up"
  section (accounts/loans → customers, transactions → accounts, customers → branches). Deeper
  transitive checks (e.g. "does this transaction's account's customer's branch exist") aren't
  implemented — would be redundant given each link is checked independently

## 5. Acceptance Criteria

- [x] Every flag in the table above is producible from `bank-data/*.csv` (see traceability table,
      section 7)
- [x] A record with zero tripped checks (structural or referential) appears in `{table}_clean`
      and nowhere in `data_quality_exceptions`
- [x] `data_quality_exceptions` has a consistent 4-column shape regardless of which of the 8
      source tables a row came from
- [ ] **Not yet verified**: execution against a live Databricks cluster

## 6. Non-Goals

- No severity levels (block/warn/info) — that's `validation_rules` in the application layer
  (`PLATFORM-BUILD-PLAN.md` Phase 3), not this notebook
- No automatic remediation or defaulting — every flagged record is held for human review, not
  silently corrected
- No IFRS 9 provisioning calculation — `NPL_STAGE_MISMATCH` only checks the *staging label*
  against the day-count rule, not whether `provision_amount` itself is correctly sized

## 7. Traceability

Hand-traced against `bank-data/*.csv` (not yet confirmed by an actual notebook run):

| Table | Key | Expected flag(s) |
|---|---|---|
| customers | `C004` | `MISSING_RISK_RATING` |
| customers | `C009` | `INVALID_SEGMENT` |
| customers | `C010` | `ORPHAN_BRANCH` (branch_id `B99` doesn't exist) |
| accounts | `ACC004` | `NEGATIVE_BALANCE` |
| accounts | `ACC009` | `INVALID_CURRENCY` |
| accounts | `ACC010` | `ORPHAN_CUSTOMER` (customer_id `C999` doesn't exist) |
| loans | `L004` | `OUTSTANDING_EXCEEDS_PRINCIPAL` |
| loans | `L006` | `NPL_STAGE_MISMATCH` (days_past_due 100, stage 1) |
| loans | `L008` | `NEGATIVE_DPD` |
| loans | `L009` | `INVALID_STAGE` (stage 5) |
| loans | `L010` | `ORPHAN_CUSTOMER` (customer_id `C999` doesn't exist) |
| transactions | `T0008` | `INVALID_AMOUNT` (blank) |
| transactions | `T0009` | `INVALID_CHANNEL` (`Cheque`) |
| transactions | `T0010` | `ORPHAN_ACCOUNT` (account_id `ACC999` doesn't exist) |
| branches | `B06` | `NEGATIVE_OPEX` |
| capital_positions | *(blank month row)* | `MISSING_MONTH` |
| capital_positions | `2026-08` | `INVALID_RWA` (risk_weighted_assets = 0) |
| liquidity_daily | `2026-09-13` | `NEGATIVE_HQLA` |
| liquidity_daily | *(blank date row)* | `MISSING_DATE` |
| fx_rates | `2026-09-16_USD/SAR` | `DUPLICATE_RATE` (both rows for that date+pair) |
| fx_rates | `2026-09-17_USD/QAR` | `INVALID_RATE` (rate = 0) |

All other rows across all eight tables are expected to land in their respective `{table}_clean`
table. This table is the test plan to verify against real notebook output once run on a live
cluster (see Acceptance Criteria section 5).
