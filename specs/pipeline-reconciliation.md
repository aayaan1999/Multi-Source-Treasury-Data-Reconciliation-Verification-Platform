# Spec: Pipeline Reconciliation per Source (FLOW-3)

**Status:** Implemented 2026-09-24: `notebooks/pipeline_reconciliation.py`, a new job task,
`load_to_postgres.py`, `db/migrations/008_pipeline_reconciliation.sql`, two backend endpoints and a
section on the Reconciliation tab. Backend, frontend and load logic tested locally; **the notebook
is not yet run on a live cluster, and migration 008 is not yet applied to Neon.**
**Backlog:** FLOW-3 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.
**Depends on:** `specs/source-tagging.md` (FLOW-1a) — every raw, clean and rejected row carries
`source_system`, `source_country`, `ingest_batch_id`.

## 1. Objective

Step 3 of the target flow agreed with the bank (2026-09-24): when data drops or changes during
cleaning (e.g. a raw total of ₹20,000 becomes ₹15,000 after checks), flag the gap as an item on
the Reconciliation tab so nothing is lost. Reconciliation is **per source**; the country is a tag.

This is **pipeline reconciliation** — did our own pipeline lose anything? It is separate from
`specs/multi-source-reconciliation.md`'s comparison with the bank's core system, which stays as
the second section of the same tab.

## 2. What is compared

For every **run + source + country + table** (one *item*):

| Measure | Received (`raw_*`, Notebook 1) | Kept (`*_clean`, Notebook 2) |
|---|---|---|
| Rows | `received_rows` | `clean_rows` |
| Amount, **per currency** (money tables only) | sum at received | sum kept |

`rejected_rows` = received − kept. Amounts are never added across currencies (USD + LBP means
nothing); each currency gets its own received / kept / gap line in `amounts_by_currency`.

| Table | Amount compared | Currency column |
|---|---|---|
| transactions | `amount` | `currency` |
| accounts | `balance` | `currency` |
| loans | `outstanding` | `currency` |
| customers, branches, capital_positions, liquidity_daily, fx_rates | rows only | — |

A missing or blank currency is shown as `UNKNOWN`, so a rejected row with a broken currency is still
visible as its own line. A row whose amount couldn't be read (`try_cast` gave null in Notebook 1)
counts as a row but adds nothing to the amount; `unreadable_amount_rows` says how many there were.

An item **has a gap** when any row was rejected or any currency's amount differs by more than
0.005. Items with a gap are `OPEN`; items without are `MATCHED` (kept, so the tab can show that a
source delivered cleanly, not only its problems).

## 3. Output: `pipeline_reconciliation`

Delta (Gold) and Neon, one row per item:

| Column | Meaning |
|---|---|
| `recon_key` | `ingest_batch_id|source_system|source_country|source_table` — unique |
| `ingest_batch_id`, `source_system`, `source_country`, `source_table` | the item |
| `received_rows`, `clean_rows`, `rejected_rows` | row counts |
| `amount_column` | e.g. `amount`; null for row-only tables |
| `unreadable_amount_rows` | rows with no readable amount |
| `amounts_by_currency` | `{"USD": {"received", "clean", "gap"}, ...}`; null for row-only tables |
| `has_gap`, `status` | `OPEN` (gap) / `MATCHED` (no gap) |
| `detected_at` | when the item was computed |
| `recon_id` | Neon only, the app's handle |

**Insert-only**, same discipline as `flagged_transactions` / `reconciliation_exceptions`: a rerun
never duplicates an item (the key includes the run) and never resets a status the app has set —
FLOW-5's CFO workflow will own `status` after first load. Each Notebook 1 run is a new delivery,
so it adds new items; earlier runs' items stay as history.

## 4. Drill-down: which records were dropped

`GET /reconciliation/pipeline/{recon_id}/records` returns the rejected records for the item from
`data_quality_exceptions` (same table, source, country and run), with each flag and reason. The
exceptions log holds only the **latest** run's rejects, so for an older run the endpoint says the
detail is no longer available instead of showing another run's records. A record can carry several
flags, so the record list can be longer than `rejected_rows`.

## 5. Screen

A new first section on the Reconciliation tab, "Received vs kept, per source":

- summary: items with a gap, rows rejected, sources delivered (latest run of each source)
- a table: source, country, table, received, kept, rejected, status; filter by country and "gaps only"
- clicking an item opens a popup: per-currency received / kept / gap lines, unreadable-amount rows,
  and the rejected records with their reasons

Read-only for now: acting on an item (CFO review, reassign, approve) is FLOW-5. The existing
core-system comparison stays below, unchanged.

## 6. Acceptance criteria

- [x]/[ ] One item per run + source + country + table, row counts and per-currency amounts as in
      section 2 — implemented; not run on a cluster
- [x]/[ ] Rerunning without a new Notebook 1 run adds nothing; a new run adds new items — implemented
      via the merge on `recon_key`; not run on a cluster
- [x] Load is insert-only and keeps an app-set status (`db/test_load_logic.py`, passes locally)
- [x] API lists the latest run's items per source, filters, and returns the rejected records only
      for the matching run (`backend/tests/test_pipeline_reconciliation.py`, passes locally)
- [x] Screen helpers: currency lines sorted biggest gap first (`frontend` vitest, passes locally)
- [ ] Migration 008 applied to Neon; job run live; screen checked in a browser

## 7. Traceability (hand-computed against `bank-data/*.csv`)

Rejections follow `specs/notebook-02-bank-data-quality.md`'s checks; countries follow
`specs/source-tagging.md`. All items share one run and `source_system` = `CORE_CSV`.

**transactions**

| Country | Received | Kept | Rejected (why) | Amounts per currency (received → kept, gap) | Status |
|---|---|---|---|---|---|
| Lebanon | T0001-T0004, T0009, T0011 (6) | 5 | T0009 (`INVALID_CHANNEL` Cheque; `ORPHAN_ACCOUNT`, ACC004 not clean) | USD 64,800 → 63,800, gap 1,000 · LBP 2,000,000 → 2,000,000 · EUR −500 → −500 | OPEN |
| Saudi Arabia | T0005, T0006, T0012-T0014 (5) | 5 | — | SAR 57,000 → 57,000 | MATCHED |
| Qatar | T0007, T0008, T0015 (3) | 2 | T0008 (`INVALID_AMOUNT`) | QAR 30,000 → 30,000, gap 0; 1 unreadable-amount row | OPEN (row gap only) |
| Unknown | T0010 (1) | 0 | T0010 (`ORPHAN_ACCOUNT`, ACC999) | USD 500 → 0, gap 500 | OPEN |

**accounts**

| Country | Received | Kept | Rejected (why) | Amounts per currency | Status |
|---|---|---|---|---|---|
| Lebanon | ACC001-ACC004, ACC009 (5) | 3 | ACC004 (`NEGATIVE_BALANCE`; C004 not clean), ACC009 (`INVALID_CURRENCY` XYZ; C009 not clean) | USD 245,000 → 250,000, gap −5,000 (the rejected balance was negative) · XYZ 50,000 → 0, gap 50,000 · LBP, EUR unchanged | OPEN |
| Saudi Arabia / Qatar | 2 / 2 | 2 / 2 | — | SAR / QAR unchanged | MATCHED |
| Unknown | ACC010 (1) | 0 | ACC010 (`ORPHAN_CUSTOMER`, C999) | USD 10,000 → 0, gap 10,000 | OPEN |

**customers:** Lebanon 5 received, 3 kept (C004 `MISSING_RISK_RATING`, C009 `INVALID_SEGMENT`) →
OPEN; Saudi Arabia 2/2 and Qatar 2/2 → MATCHED; Unknown 1 received (C010), 0 kept
(`ORPHAN_BRANCH`, B99) → OPEN. **branches:** Lebanon 4 received, 3 kept (B06 `NEGATIVE_OPEX`) →
OPEN; Saudi Arabia 1/1, Qatar 1/1 → MATCHED.

The accounts USD line shows why gaps are signed: dropping a negative balance makes the kept total
*larger* than the received one. Hand-computed, not verified by an actual run.

## 8. Open items

1. **Repeated gaps:** every new run of a source with the same broken record creates a new OPEN item.
   When FLOW-5 creates tasks from items, it should link or supersede the previous run's open item
   rather than open a second task.
2. **Which amounts matter** (question 2 for the bank): balances and loan outstanding are compared
   today alongside transaction amounts; the bank may want a different set.
3. Received counts come from `raw_*`, i.e. after Notebook 1 has parsed the file. A line the CSV
   reader couldn't parse at all would not be counted; a file-level row count (before parsing) is a
   later addition if a source can send malformed files.

## 9. Completeness check (FLOW-1b)

Items only exist for rows that arrived, so an empty file, or a country missing from a file, would
leave no trace. `EXPECTED_DELIVERIES` in the notebook lists the countries each source must deliver
every run (today: `CORE_CSV` → Lebanon, Saudi Arabia, Qatar); bank-wide tables are expected once
under `Group`. Every expected country × table with no item gets an item with 0 rows,
`note` = "No rows delivered", `has_gap` true → OPEN → a CFO task like any other gap
(migration 011 adds `note`).

- A **missing CSV file** already stops Notebook 1 with an error, so it can't pass silently.
- A source not in `EXPECTED_DELIVERIES` is still reconciled, just not checked for missing countries.
- Not covered yet: a source that doesn't deliver **at all** in a run (no run id to attach an item
  to) and delivery **cut-off times** — both matter once several sources deliver separately (for the
  demo every source is a CSV drop in one folder).
