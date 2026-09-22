# Spec: Multi-Source Reconciliation

**Status:** Neon slice written, not yet run against a live cluster — blocked on the same external
setup `multi_source_neon_ingestion.py` needs (a demo Neon source project, deliberately seeded with
matches/mismatches per section 4) which hasn't been done. `reconciliation_exceptions` exists in
Neon (`db/schema.sql`, `db/migrations/002_reconciliation_exceptions.sql`, applied) and
`load_to_postgres.py` merges it with the same insert-only discipline as `flagged_transactions`.
Mockaroo and Salesforce (section 3) remain spec-only — starting with Neon only was a deliberate
scope decision, not a partial failure.
**New for:** closing the actual reconciliation gap in this project's own name. See "Are We Doing
Reconciliation?" discussion in-session, 2026-09-22.
**File:** `notebooks/multi_source_reconciliation.py` — written.
**Depends on:** `specs/notebook-02-bank-data-quality.md` (`*_clean` canonical tables) and
`specs/multi-source-ingestion-adf.md` (the 5 `bronze_*` source tables) — see section 6 for exactly
which of those five this spec actually uses.

---

## 1. Objective

**Verification (Notebook 2, already built) checks whether one row is internally consistent** —
is `risk_rating` null, does a loan's `stage` match its `days_past_due`, does a foreign key resolve.
It never compares two independent systems' account of the same fact.

**Reconciliation is a different question: do two independent sources agree on the same
real-world fact, and if not, which one is right?** This is what the original brief this project is
named after specified (`CROSS_ENTITY_MISMATCH`, `RECONCILIATION_MISMATCH` — see `bank-x
poc-brief.md` section on Notebook 2/3) before the schema rewrite to the bank-wide model dropped it.
It was never rebuilt against the new schema. This spec rebuilds it, scoped to the multi-source
ingestion architecture that actually exists today.

Output: `reconciliation_exceptions`, a table of field-level disagreements between a `bronze_*`
source and the canonical `*_clean` record it claims to describe, each with a mutable `status` for
manual review — same "auto-flag, human decides" pattern as `flagged_transactions`
(`specs/notebook-05-fraud-business-rules.md`) and `data_quality_exceptions`
(`specs/notebook-02-bank-data-quality.md`).

## 2. Why a Separate Notebook, Not Part of Notebook 2 or the Ingestion Notebooks

Same reasoning as `specs/notebook-05-fraud-business-rules.md` section 2, one level up: Notebook 2
validates one row against rules; this notebook compares two rows (one canonical, one from an
external source) against each other. Putting it inside a `multi_source_*_ingestion` notebook would
mean each of the 5 ingestion notebooks re-implements its own comparison logic against a moving
target (the canonical tables); putting it inside Notebook 2 would conflate "is this row broken" with
"do two systems disagree about this row" — different downstream handling, same distinction
`specs/notebook-05-fraud-business-rules.md` already draws for fraud vs. data quality.

This notebook runs **after** Notebook 2 (needs `*_clean` as the canonical side of the comparison)
and after whichever `multi_source_*_ingestion` notebooks it reconciles against (needs their
`bronze_*` output as the other side).

## 3. Scope Decision: Which Sources Actually Get Reconciled

Not all 5 multi-source ingestion notebooks describe entities the canonical tables also hold —
reconciliation only makes sense where both sides claim to describe the *same* real-world thing.

| # | Source | Stands in for | Reconcile against | Why |
|---|---|---|---|---|
| 1 | Neon | Core Banking System | `customers_clean`, `accounts_clean` | Same entity type as canonical — a second system's account of the same customers/accounts |
| 2 | Mockaroo | Loan Origination System | `loans_clean` | A loan should agree between the origination system and whatever's servicing it |
| 4 | Salesforce | CRM | `customers_clean` (name/contact fields only) | CRM and core banking should agree on who a customer is |
| 3 | IMF Data API | Regulatory/macro feed | **Not reconciled** | Describes currencies/countries, not this bank's customers/loans/accounts — no canonical counterpart to compare against |
| 5 | Google Sheets | Branch/Finance ERP | **Not reconciled** | Branch opex/staffing has no independent second source in this schema to reconcile against — it *is* the source for `branches.monthly_opex`, not a duplicate of one |

This is a deliberate scope cut, not an oversight: reconciling IMF or Google Sheets data would mean
inventing a second source to compare them against, which doesn't exist. If a second branch-cost
feed or macro-data feed is ever added, reconciliation logic could extend to them then.

## 4. A Real Dependency This Spec Cannot Resolve on Its Own

Reconciliation needs the two sides to reference the same entity by a **shared key** —
`customer_id`, `loan_id`. Mockaroo and Salesforce are mock/demo systems with schemas *you* design;
nothing guarantees their generated records' IDs overlap with the canonical tables' IDs unless
that's done deliberately when the mock schema/data is set up.

**This means reconciliation is only demonstrable once the demo source data is deliberately seeded
with a mix of:** matching records (same ID, same values — reconciles clean), matching records with
a deliberately different field value (same ID, different amount/name — should produce a
`VALUE_MISMATCH`), and records that exist on only one side (`MISSING_IN_*`). This is the same
technique `bank-data/*.csv` already uses to exercise Notebook 2's checks (a few rows are
deliberately broken) — the mock sources need the same treatment before this notebook has anything
real to find. **Not resolvable in this notebook's code; it's a data-setup step that has to happen
in Mockaroo's/Salesforce's own UI first.**

## 5. Matching and Mismatch Rules

For each pair in section 3, per matched record:

| Condition | Result |
|---|---|
| Record exists on both sides, all compared fields equal (within tolerance for numeric fields) | No exception row — reconciled clean |
| Record exists on both sides, a compared field differs beyond tolerance | `VALUE_MISMATCH`, one row per mismatched field |
| Record's key exists in the `bronze_*` source but not in the canonical table | `MISSING_IN_CANONICAL` — the source claims a record we don't have |
| Record's key exists in the canonical table but not in the `bronze_*` extract | `MISSING_IN_SOURCE` — could be a legitimate extract-timing lag (the source hasn't synced yet), not necessarily an error; flagged at lower severity than `VALUE_MISMATCH` |

**Numeric tolerance** (amounts, balances): differences under $1.00 (or the row's own currency
equivalent) don't flag — rounding noise, not a real mismatch. This mirrors the "within tolerance"
language in the original brief's `RECONCILIATION_MISMATCH` rule. **Text fields** (name, segment):
exact match only for this POC — no fuzzy/normalized comparison (see section 8).

Compared fields per pair:

| Pair | Canonical table | Compared fields |
|---|---|---|
| Neon customers | `customers_clean` | `name`, `segment`, `risk_rating`, `branch_id` |
| Neon accounts | `accounts_clean` | `type`, `currency`, `balance` |
| Mockaroo loans | `loans_clean` | `customer_id`, `principal`, `product`, `origination_date` |
| Salesforce customers | `customers_clean` | `name` only (Salesforce's mock Account/Contact schema doesn't carry segment/risk_rating) |

## 6. Output

Delta table `reconciliation_exceptions`, MERGEd (not overwritten) into Postgres by
`load_to_postgres.py` — same status-preserving discipline as `flagged_transactions`:

| Column | Type | Notes |
|---|---|---|
| `exception_id` | bigserial (Postgres) / generated at load | app-side handle, same pattern as `data_quality_exceptions.exception_id` |
| `source_system` | string | `neon`, `mockaroo`, `salesforce` |
| `entity_type` | string | `customer`, `account`, `loan` |
| `entity_id` | string | the shared key (`customer_id` / `account_id` / `loan_id`) |
| `field_name` | string | null for `MISSING_IN_*` rows (whole record is missing, not one field) |
| `source_value` | string | null for `MISSING_IN_SOURCE` |
| `canonical_value` | string | null for `MISSING_IN_CANONICAL` |
| `mismatch_type` | string | `VALUE_MISMATCH`, `MISSING_IN_CANONICAL`, `MISSING_IN_SOURCE` |
| `status` | string | `OPEN` (default) / `ACCEPTED` / `CORRECTED` / `DISMISSED` — see section 7 |
| `detected_at` | timestamp | `current_timestamp()` at notebook run time |
| `resolved_by`, `resolved_at`, `resolution_note` | string / timestamp / string | set by manual review, null until then |

**`status` and the `resolved_*` columns are initialise-only from this notebook**, exactly like
`flagged_transactions.status` — a rerun must `MERGE ... WHEN NOT MATCHED INSERT`, never overwrite
a row a reviewer already actioned.

## 7. Manual Intervention

Reuses the existing "flag → review → status" UX pattern already built for `data_quality_exceptions`
and `flagged_transactions` rather than inventing a new one:

- **`OPEN`** — auto-detected, awaiting review (default).
- **`ACCEPTED`** — a reviewer confirms the two sources are both right for a known reason (e.g. a
  timing difference that's expected), no data changes.
- **`CORRECTED`** — a reviewer determines the canonical record is wrong. **This notebook never
  writes back to `customers`/`accounts`/`loans` automatically** — correcting the canonical record
  is a separate, deliberate action a human takes elsewhere (or a follow-up ticket), not something
  this pipeline does silently. Auto-correcting production data from an unverified mock/demo source
  would be exactly the kind of silent, unreviewed data change this whole platform exists to
  prevent.
- **`DISMISSED`** — false positive (e.g. a text field mismatch that's actually fine — a
  legal-name abbreviation, not a real disagreement).

Surfacing this in the app is a UI follow-up, not part of this spec — it slots naturally next to
the existing exception views (or Screen 6's task queue once that's built) rather than needing a
new screen.

## 8. Non-Goals

- **No fuzzy/probabilistic matching.** Exact key match only. Real entity resolution (matching
  "Khalil Trading SAL" against "Khalil Trading S.A.L." as the same customer) is a materially
  different, harder problem — out of scope for this POC.
- **No automatic write-back/correction** to canonical tables (section 7).
- **IMF and Google Sheets sources are not reconciled** (section 3) — they have no canonical
  counterpart to compare against in the current schema.
- **No reconciliation between the 5 sources and each other** (e.g. Mockaroo vs. Salesforce
  directly) — only source-vs-canonical, matching the original brief's framing of reconciling
  against a "single consolidated view," not an all-pairs comparison.
- **Not a general MDM (master data management) engine.** This is a POC-scale demonstration of the
  mechanism (compare → flag → review), not a production reconciliation platform.

## 9. Acceptance Criteria

- [x] `notebooks/multi_source_reconciliation.py` written, reading `customers_clean`,
      `accounts_clean` and `bronze_neon_customers`/`bronze_neon_accounts` (the Neon slice only —
      Mockaroo/Salesforce/`loans_clean` are section 3's deferred scope, not yet written)
- [ ] Each rule in section 5 produces the correct `mismatch_type` against deliberately-seeded
      mock data (section 4) — blocked on provisioning the demo Neon source project
      `multi_source_neon_ingestion.py` needs and seeding it with intentional matches, mismatches,
      and missing records; not run against a live cluster yet
- [x] Rerun-safe by construction: `DeltaTable.merge(...).whenNotMatchedInsertAll()` (same mechanism
      as `flagged_transactions`) — not yet exercised by an actual second run with a pre-existing
      reviewed row
- [x] `db/schema.sql` has a `reconciliation_exceptions` table matching section 6; applied to Neon
      via `db/migrations/002_reconciliation_exceptions.sql` (confirmed idempotent — applied twice)
- [x] `load_to_postgres.py` merges `reconciliation_exceptions` using the same insert-only,
      status-preserving rule as `flagged_transactions` (`ON CONFLICT ... DO NOTHING`, exempted from
      the rows-merged-must-equal-rows-staged check)

Nothing above is implemented yet — this is a spec to review and scope, not a built feature.

## 10. Open Questions for the Client / Project Owner

- Confirm the field-level tolerance in section 5 (the $1.00 numeric threshold is illustrative,
  same caveat as `specs/notebook-05-fraud-business-rules.md`'s $50,000 large-amount threshold).
- Confirm which of the 3 reconcilable sources (Neon, Mockaroo, Salesforce) to build and seed
  first — doing all three before any of them is demoed risks the same "written but unrun" state
  several `multi_source_*_ingestion` notebooks are already in.
- Decide where `CORRECTED` resolutions actually get actioned (a manual DB edit? a follow-up
  ticket in some other system?) — this spec deliberately leaves that outside the pipeline, but the
  real workflow needs an answer.
