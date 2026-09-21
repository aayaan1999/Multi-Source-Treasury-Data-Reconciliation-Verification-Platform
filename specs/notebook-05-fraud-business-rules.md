# Spec: Notebook 5 — Fraud & Business Rule Detection

**Status:** Spec only — not yet implemented
**New for:** the 3-week Camunda-based POC extension — see `3-WEEK-POC-PLAN.md`
**Source of truth:** user-provided "Proposed End-to-End Process" (Step 2: "Fraud/business rules
identify fraudulent or faulty transactions. Each problematic transaction can be assigned a
fault/fraud type and status.")
**File (planned):** `notebooks/05_fraud_business_rules.py`
**Depends on:** `specs/notebook-02-bank-data-quality.md` (reads `transactions_clean`)

---

## 1. Objective

Run fraud- and business-rule checks against `transactions_clean` (Notebook 2's Silver-layer
output) and produce `flagged_transactions`, a table with a **type** (`FRAUD` vs `FAULT`) and a
mutable **status** field — the input Camunda's process needs to create and route review tasks (see
`specs/camunda-bpmn-process-design.md`). In medallion terms, `flagged_transactions` sits between
Silver and Gold: it's an enrichment of Silver-layer `transactions_clean` (not a re-validation of
structure — that's Notebook 2's job), and it in turn feeds toward Gold consumers (Screen 6's task
queue, and any future Gold-layer fraud rollups).

## 2. Why a Separate Notebook, Not an Extension of Notebook 2

Notebook 2 checks **data quality** (is this row structurally valid — missing/malformed/orphaned).
Fraud/business rules ask a different question: **is this a real, well-formed transaction that
still looks wrong** (unusually large, suspiciously patterned, duplicated). Conflating the two
would mean a single `flags` array mixing "the data is broken" with "the data is fine but
suspicious" — different downstream handling (a broken record needs data correction; a suspicious
one needs an investigator's judgment). Keeping them as separate notebooks/tables keeps that
distinction explicit and matches the medallion framing established in `specs/notebook-01-bank-
data-ingestion.md` (Bronze) and `specs/notebook-02-bank-data-quality.md` (Silver): this notebook
reads Silver, adds a business-rule enrichment layer on top, and its output feeds toward Gold.

## 3. Rules

All four rules operate on `transactions_clean`. USD conversion (where needed) follows the same
"latest valid rate from `fx_rates_clean`" methodology as `specs/notebook-03-kpi-summary.md`
section 4.

| Flag | Type | Condition | Threshold (POC value, configurable) |
|---|---|---|---|
| `LARGE_AMOUNT` | FRAUD | `ABS(amount)` (USD-converted) exceeds a threshold | 50,000 USD |
| `VELOCITY_BREACH` | FRAUD | More than 2 transactions for the same `account_id` on the same `date` | count > 2 |
| `STRUCTURING_PATTERN` | FRAUD | `ABS(amount)` (native currency) falls in the band just under a round reporting threshold, for an account with 2+ such transactions on the same date | 8,500 ≤ amount < 10,000 (illustrative; a real reporting threshold is jurisdiction-specific and should come from the client, not be hardcoded here) |
| `DUPLICATE_TRANSACTION` | FAULT | Another row shares the same `account_id`, `amount`, `currency`, `type`, and `date` (different `transaction_id`) | exact match on those 5 fields |

**These are illustrative POC rules, not a validated fraud model.** Real fraud detection
typically also needs: customer-level behavioral baselines (is this unusual *for this customer*,
not just unusual in absolute terms), cross-account/cross-entity pattern detection, and ML-based
anomaly scoring — all explicitly out of scope here. This notebook demonstrates the *mechanism*
(flag → type → status → task), not a production fraud engine.

## 4. Schema Gap: No Transaction Timestamp

`transactions.date` is a **date**, not a datetime (see `Middle East bank data cleaning and
reporting.md`'s `transactions` table definition). Several genuinely useful fraud rules —
same-hour velocity, off-hours activity, rapid-succession transfers — need time-of-day precision
this schema doesn't have. `VELOCITY_BREACH` above is deliberately scoped to same-*day* velocity
as a result, which is a much weaker signal than same-*hour* velocity would be. **Recommend adding
a `timestamp` column (or splitting `date` into `transaction_datetime`) to the source schema** if
finer-grained fraud rules are wanted — flagging this rather than faking hour-level detection off
a date-only column.

## 5. Output

Delta table `flagged_transactions`:

| Column | Type | Notes |
|---|---|---|
| `transaction_id` | string | |
| `flag_label` | string | `LARGE_AMOUNT`, `VELOCITY_BREACH`, `STRUCTURING_PATTERN`, `DUPLICATE_TRANSACTION` |
| `flag_type` | string | `FRAUD` or `FAULT` |
| `description` | string | human-readable, same pattern as Notebook 2's exceptions |
| `status` | string | initialised to `PENDING_REVIEW`; updated by the bidirectional sync (`specs/bidirectional-sync.md`), never mutated directly by this notebook after first creation |
| `detected_at` | timestamp | `current_timestamp()` at notebook run time |

**Status is initialise-only from this notebook.** Once a row exists in `flagged_transactions`,
subsequent runs must not overwrite its `status` if it's already been reviewed (`MERGE`, not
`overwrite`) — otherwise a reviewer's decision would be silently reset every time this notebook
reruns. This is the one notebook in the pipeline that isn't a clean overwrite-on-rerun.

## 6. Acceptance Criteria

- [x] Written: `notebooks/05_fraud_business_rules.py`. **Not yet run against a live cluster** —
      none of the below is verified by an actual run.
- [ ] Every rule in section 3 fires correctly against `bank-data/transactions.csv` (see
      traceability, section 7)
- [x]/[ ] A transaction can carry multiple flags (e.g. both `STRUCTURING_PATTERN` and
      `VELOCITY_BREACH`) — implemented via `unionByName` across the 4 rules, each contributing
      its own row(s); not yet verified against the traceability table
- [x]/[ ] Rerunning the notebook does not reset `status` on a row a reviewer has already actioned
      — implemented via `MERGE INTO ... WHEN NOT MATCHED INSERT`, not `overwrite`; not yet
      verified by an actual rerun against a cluster with a pre-existing reviewed row
- [x]/[ ] `LARGE_AMOUNT`'s USD conversion uses `fx_utils.get_live_rate()` per
      `specs/fx-realtime-ingestion.md`'s platform-wide move off `fx_rates_clean`, even though that
      spec's acceptance criteria only names Notebooks 3/6 explicitly — not yet verified

## 7. Traceability (hand-computed against `bank-data/transactions.csv`)

| transaction_id | account_id | Expected flag(s) |
|---|---|---|
| `T0011` | ACC001 | `LARGE_AMOUNT` (60,000 USD > 50,000 threshold) |
| `T0012` | ACC005 | `STRUCTURING_PATTERN` (9,500 SAR in band), `VELOCITY_BREACH` (3 txns on 2026-09-09 for ACC005) |
| `T0013` | ACC005 | `STRUCTURING_PATTERN`, `VELOCITY_BREACH` (same date/account as T0012) |
| `T0014` | ACC005 | `STRUCTURING_PATTERN`, `VELOCITY_BREACH` (same date/account as T0012/T0013) |
| `T0015` | ACC007 | `DUPLICATE_TRANSACTION` (matches `T0007`: ACC007, 15000, QAR, Deposit, 2026-09-01) |

All other clean transactions (`T0001`-`T0006`) are expected to produce zero flags. `T0007`-`T0010`
either don't reach `transactions_clean` (missing amount, invalid channel, orphan account — see
`specs/notebook-02-bank-data-quality.md`) or, for `T0007`, is clean but untouched by any fraud
rule on its own (it only becomes relevant as `T0015`'s duplicate match).

These are hand-computed, not verified by an actual run — same caveat as every other spec in this
repo.

## 8. Non-Goals

- No customer-level behavioral baselining (needs historical data volume this POC doesn't have)
- No ML-based anomaly scoring
- No real reporting-threshold value — the 10,000 structuring band is illustrative, not sourced
  from an actual regulator requirement
