# Spec: Day 1 — Sample Data + Notebook Scaffolding

**Status:** Implemented (sample CSVs + Notebooks 1-2 built; Notebooks 3-4 remain — see Open Items)
**Plan reference:** `7-DAY-PLAN.md` → Day 1
**Owner:** Dev Lead (sample data) + Claude Code (notebooks)
**Depends on:** `bank-x poc-brief.md` sections 4-5

---

## 1. Objective

Produce the raw inputs and the first two Databricks notebooks needed to prove the treasury
data-quality pipeline works, end to end, on realistic-but-small synthetic data. This is the
foundation the rest of the Databricks layer (Notebooks 3-4) and, later, the application layer's
Phase 2 (`PLATFORM-BUILD-PLAN.md`) build on.

## 2. Scope

**In scope:**
- Three entity source CSVs with deliberately injected data-quality issues
- Notebook 1 (Ingestion & Standardisation)
- Notebook 2 (Data Quality Verification)

**Out of scope (separate specs when work resumes):**
- Notebook 3 (Reconciliation & Consolidated Report)
- Notebook 4 (Exception Summary Report)
- Running the notebooks against a live Databricks cluster (environment not yet provisioned —
  see `DATABRICKS-SETUP.md`)
- Anything in the application layer

## 3. Deliverable 1 — Sample Entity CSVs

### 3.1 Requirements (from brief section 4)

Three files, one per entity, sharing a base schema but each with entity-specific quirks:

| File | Entity | Home currency | Date format | Notes |
|---|---|---|---|---|
| `lebanon_positions.csv` | LEB | USD | `YYYY-MM-DD` | baseline schema |
| `ksa_positions.csv` | KSA | SAR | `DD/MM/YYYY` | some currency pairs written without a `/` (e.g. `USDSAR`); trader IDs in a different format (`KSA-####`) |
| `qatar_positions.csv` | QAT | QAR | `YYYY-MM-DD` | notional column named `trade_amt` instead of `notional_amount`; contains a duplicate `trade_id` |

**Common columns:** `trade_id, trade_date, entity_code, currency_pair, position_type,
notional_amount (or trade_amt for Qatar), base_currency_amount, counter_currency_amount,
trader_id, limit_threshold, data_source`

**Injected issues, spread across the three files (brief target ranges in parentheses):**
- Missing values (3-5 per file): missing `trade_date`, missing `trader_id`, missing
  `position_type`/`notional_amount` depending on file
- Format mismatches (2-3 per file): invalid currency-pair codes (`XYZ/USD`, `QR/USD`), no-slash
  pairs KSA-side (`USDSAR`, `QARSAR`), non-numeric notional text (`"eighty thousand"`, `"n/a"`)
- Limit breaches (1-2 per file): `notional_amount > limit_threshold`
- Duplicate record (1, in Qatar): exact duplicate row sharing `trade_id`
- Cross-entity inconsistency (1, across Lebanon + KSA): same `trade_id` (`TRD-2001`), different
  `base_currency_amount` when converted to USD

### 3.2 Acceptance Criteria

- [x] All three CSVs exist at repo root with the column layouts above
- [x] Every issue category from brief section 4 is represented at least once, traceable by row
- [x] `TRD-2001` appears in both `lebanon_positions.csv` and `ksa_positions.csv` with a genuine
      USD-equivalent mismatch (not just a currency-notation difference)
- [x] Row counts stay small (10-11 rows/file) — files must be demo-scannable by eye, not a stress
      test (per `7-DAY-PLAN.md` discussion: large volume is explicitly deferred to a later,
      separate "stress-test dataset" if ever needed)

### 3.3 Files produced

`lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv` (repo root)

---

## 4. Deliverable 2 — Notebook 1: Ingestion & Standardisation

### 4.1 Requirements (from brief section 5)

- Read all three entity CSVs
- Standardise column names to one common schema (Qatar's `trade_amt` → `notional_amount`)
- Standardise dates to `YYYY-MM-DD` (handle both `YYYY-MM-DD` and `DD/MM/YYYY` inputs)
- Standardise currency-pair notation to `XXX/YYY` (insert `/` into clean 6-letter codes; leave
  genuinely invalid codes untouched for Notebook 2 to catch)
- Convert all amount columns to USD equivalent via a hardcoded FX rate table (no live feed)
- Add `entity_code` defensively if a source file ever omits it
- Output: Delta table `treasury_positions_raw`
- Inline comments explaining each transformation step (explicit brief requirement)

### 4.2 Design decisions made

- FX conversion is keyed off each entity's **home currency** (LEB→USD, KSA→SAR, QAT→QAR), not
  parsed out of the (possibly malformed) `currency_pair` column — avoids circular dependency on
  data that hasn't been validated yet
- Non-numeric amounts are cast via `try_cast` to null rather than dropped — nothing is silently
  discarded at this stage; nulls flow downstream for Notebook 2 to flag
- `input_dir` and `output_table` are notebook widgets, not hardcoded paths, so the Databricks
  Developer can point at their actual environment without editing code

### 4.3 Acceptance Criteria

- [x] Reading all three CSVs and unioning them (via `unionByName(allowMissingColumns=True)`)
      produces one DataFrame with every source row present
- [x] `TRD-1006` (`"eighty thousand"`) and `TRD-3007` (`"n/a"`) resolve to null `notional_amount`
      after ingestion, not an error or a dropped row
- [x] KSA rows' `USDSAR` becomes `USD/SAR`; Qatar's `USDQAR` becomes `USD/QAR`; genuinely invalid
      codes (`XYZ/USD`, `QR/USD`) are left unchanged
- [x] All KSA dates (`DD/MM/YYYY`) parse to valid `trade_date` values equal to their Lebanon/Qatar
      (`YYYY-MM-DD`) counterparts' format
- [ ] **Not yet verified**: actual execution against a live Databricks cluster (blocked on
      environment setup — see `DATABRICKS-SETUP.md`); everything above has been traced by hand
      against the sample CSVs, not run

### 4.4 File produced

`notebooks/01_ingestion_standardisation.py`

---

## 5. Deliverable 3 — Notebook 2: Data Quality Verification

### 5.1 Requirements (from brief section 5)

Run 8 checks against every row of `treasury_positions_raw`, each producing a distinct flag label:

| Check | Flag Label |
|---|---|
| Missing `trade_date` | `MISSING_DATE` |
| Missing `trader_id` | `MISSING_TRADER` |
| Invalid currency-pair format | `INVALID_CCY_PAIR` |
| Notional amount non-numeric or zero | `INVALID_AMOUNT` |
| Counter amount doesn't reconcile to notional within tolerance | `RECONCILIATION_MISMATCH` |
| Position exceeds `limit_threshold` | `LIMIT_BREACH` |
| Duplicate `trade_id` within same entity | `DUPLICATE_RECORD` |
| Same `trade_id` across two entities with different amount | `CROSS_ENTITY_MISMATCH` |

Output: `treasury_positions_clean` (rows tripping zero checks), `treasury_positions_exceptions`
(one row per tripped check, with flag label + description).

### 5.2 Design decisions made

- A row can trip multiple checks; each becomes its own exception row (via `explode`) rather than
  collapsing to one flag per row — a reviewer needs to see every issue, not just the first one found
- `INVALID_CCY_PAIR` only fires on pairs still malformed *after* Notebook 1's slash-insertion fix —
  it tests genuinely invalid codes, not formatting Notebook 1 already normalized
- `RECONCILIATION_MISMATCH` uses a per-pair expected rate table (`PAIR_EXPECTED_RATE`) with a 5%
  tolerance; a pair with no known rate is skipped by this check rather than flagged, since there's
  no basis to judge it
- `CROSS_ENTITY_MISMATCH` compares `base_currency_amount_usd` pairwise across entities sharing a
  `trade_id`, also at 5% tolerance

### 5.3 Acceptance Criteria

- [x] Every one of the 8 flag labels is producible from the sample data (traced by hand against
      each injected issue in section 3.1)
- [x] `TRD-1008` (Lebanon) and `TRD-4005` (Qatar) trip `RECONCILIATION_MISMATCH`
- [x] `TRD-2001` trips `CROSS_ENTITY_MISMATCH` (Lebanon vs. KSA base amount disagreement)
- [x] `TRD-4009` (Qatar, duplicated row) trips `DUPLICATE_RECORD` on both copies
- [x] A row with zero tripped checks appears only in `treasury_positions_clean`, never in
      `treasury_positions_exceptions`
- [ ] **Not yet verified**: actual execution against a live Databricks cluster (same caveat as 4.3)

### 5.4 File produced

`notebooks/02_data_quality_verification.py`

---

## 6. Non-Goals for Day 1

- No FX/scenario/regulatory logic (that's Notebooks 3-4 and the application layer)
- No PostgreSQL, FastAPI, or React work
- No live cluster execution — this spec's acceptance criteria were verified by hand-tracing logic
  against the sample data, not by running the notebooks

## 7. Open Items Before This Spec Is Fully Closed

1. Run Notebooks 1-2 against an actual Databricks cluster (Community Edition or Azure — see
   `DATABRICKS-SETUP.md`) and confirm the traced results above hold in practice
2. Resolve `bank-x poc-brief.md` section 11 environment questions (runtime version, Delta Lake
   availability) if using Azure rather than Community Edition

## 8. Traceability

| Sample row | Entity | Expected flag(s) |
|---|---|---|
| `TRD-1003` | LEB | `MISSING_DATE` |
| `TRD-1004` | LEB | `INVALID_CCY_PAIR` |
| `TRD-1005` | LEB | *(none)* — row has a missing `position_type`, but no check in the 8 covers that field; `trader_id` and amounts are otherwise valid and reconcile, so this row lands in `treasury_positions_clean`, not exceptions |
| `TRD-1006` | LEB | `INVALID_AMOUNT` |
| `TRD-1008` | LEB | `RECONCILIATION_MISMATCH` |
| `TRD-1009` | LEB | `MISSING_TRADER`, `LIMIT_BREACH` |
| `TRD-1010` | LEB | `LIMIT_BREACH` |
| `TRD-2001` (LEB + KSA) | LEB, KSA | `CROSS_ENTITY_MISMATCH` on both |
| `TRD-3004` | KSA | `MISSING_DATE` |
| `TRD-3005` | KSA | `MISSING_TRADER` |
| `TRD-3007` | KSA | `INVALID_AMOUNT` |
| `TRD-3008` | KSA | `LIMIT_BREACH` |
| `TRD-3009` | KSA | `INVALID_AMOUNT` (missing notional) |
| `TRD-4003` | QAT | `LIMIT_BREACH` |
| `TRD-4004` | QAT | `MISSING_DATE` |
| `TRD-4005` | QAT | `RECONCILIATION_MISMATCH` |
| `TRD-4006` | QAT | `MISSING_TRADER` |
| `TRD-4007` | QAT | `INVALID_CCY_PAIR` |
| `TRD-4008` | QAT | `INVALID_AMOUNT` |
| `TRD-4009` (both copies) | QAT | `DUPLICATE_RECORD` |

**Note:** this table was built by tracing the notebook logic against the sample CSVs by hand, not
by actually running the notebook. Treat this section as a test plan to verify against real output
in Open Item 1, not as confirmed fact.
