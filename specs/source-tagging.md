# Spec: Source Tagging (FLOW-1a)

**Status:** Implemented 2026-09-24 in Notebooks 1 and 2, `load_to_postgres.py` and
`db/migrations/007_source_tagging.sql`. Hand-traced only — **not yet run on a live cluster, and
migration 007 not yet applied to Neon.**
**Backlog:** FLOW-1a in `project-docs/CLIENT-FEEDBACK-BACKLOG.md` (same work as SRC-1).

## 1. Objective

Every record says where it came from, so the next step (FLOW-3, reconciliation per source) can
compare what each source sent with what survived cleaning. The target flow agreed with the bank
(2026-09-24) has 10 countries, each with its own systems (ERP, CRM, ...); reconciliation is done
**per source**, and the country is a tag on the source, used for dashboards, filters and routing.

## 2. The four tag columns

Stamped by Notebook 1 on every row of every `raw_*` table, kept by Notebook 2 on every
`*_clean` row and every `data_quality_exceptions` row, and loaded into the matching Neon tables.

| Column | Meaning | Today's value |
|---|---|---|
| `source_system` | The system that sent the record | `CORE_CSV` (placeholder: one source for the current CSV set) |
| `source_country` | The country the record belongs to | See section 3 |
| `ingest_batch_id` | The Notebook 1 run that loaded it | e.g. `CORE_CSV-20260924T104200Z-3f9a1c2e` |
| `source_file` | The file the record was read from | e.g. `transactions.csv` |

`source_country` is deliberately **not** called `country`: `customers.csv` already has a `country`
column (the customer's own country, e.g. "Saudi Arabia"), which is a different fact.

`ingest_batch_id` is one value for the whole Notebook 1 run (all 8 files). A run is the unit
FLOW-3 reconciles, so every row of one run shares it.

## 3. How `source_country` is set

Notebook 1 takes two parameters (widgets): `source_system` (default `CORE_CSV`) and
`source_country` (default blank).

- **A single-country source** (the future case: e.g. `input_dir` = Lebanon ERP's landing folder,
  `source_country` = `Lebanon`): every row gets that country.
- **A multi-country source** (today: blank parameter): each row gets the country of its branch:

  | Record | Country comes from |
  |---|---|
  | branches | its own `region` |
  | customers | its `branch_id` → branch region |
  | accounts, loans | its `customer_id` → customer → branch |
  | transactions | its `account_id` → account → customer → branch |
  | capital_positions, liquidity_daily, fx_rates | `Group` (bank-wide figures, no branch) |

  Region → country, `REGION_COUNTRY` in Notebook 1 (**an assumption from the region names in the
  sample data — confirm with the bank**): Beirut, North, South, Bekaa, Mount Lebanon → Lebanon;
  KSA → Saudi Arabia; Qatar → Qatar. A record whose branch can't be found (missing or orphan
  key), or whose region isn't in the map, gets `Unknown` — never dropped here; Notebook 2's orphan
  checks still judge the record itself.

The lookups run on the **raw** tables (Notebook 1 runs before any cleaning) and are de-duplicated
per key first, so a duplicated parent key can never multiply child rows.

## 4. Other changes

- **Notebook 2:** clean tables keep the tags automatically (every check selects `*`). The
  exceptions log gains the same four columns, taken from the rejected row — including orphans
  (`orphan_flags`) — so a rejected record still shows its source.
- **`load_to_postgres.py`:** no code change for entity tables (the merge copies every column that
  exists in both staging and Neon). `data_quality_exceptions`' upsert now also refreshes the four
  tags, since a persisting exception is re-found by every run.
- **Neon:** migration 007 adds the four nullable columns to the 8 entity tables and
  `data_quality_exceptions`. Nullable, so a load from an older Notebook 1 still works.
- **Screens:** none yet. The Tasks review panel's "Correct" field list hides the four tags (they
  describe provenance and aren't values a reviewer should correct). Showing the source on
  drill-downs is SRC-2.

## 5. Acceptance criteria

- [x]/[ ] Every `raw_*` row carries all four tags — implemented; not run on a cluster
- [x]/[ ] `source_country` follows section 3 for a multi-country source and is the parameter's
      value for a single-country one — implemented; not run on a cluster
- [x]/[ ] No row count change in any `raw_*` table from the country lookups — implemented via
      de-duplicated left joins; not run on a cluster
- [x]/[ ] `*_clean` and `data_quality_exceptions` carry the tags from the source row — implemented;
      not run on a cluster
- [x] Neon columns + load: `db/test_load_logic.py` loads tagged staging rows and checks the tags
      land, and that a persisting exception's tags are refreshed (passes locally)
- [ ] Migration 007 applied to Neon
- [ ] Verified end to end on a live run

## 6. Traceability (hand-computed against `bank-data/*.csv`, multi-country mode)

| Record | Path | `source_country` |
|---|---|---|
| Branches B01 / B02, B06 / B03 | region Beirut / North / South | Lebanon |
| Branch B04 | region KSA | Saudi Arabia |
| Branch B05 | region Qatar | Qatar |
| Customers C001, C002 (B01), C003, C009 (B02), C004 (B03) | → branch | Lebanon |
| Customers C005, C006 (B04) | → branch | Saudi Arabia |
| Customers C007, C008 (B05) | → branch | Qatar |
| Customer C010 | branch B99 doesn't exist | Unknown (and still flagged `ORPHAN_BRANCH` by Notebook 2) |
| Accounts ACC001-ACC004, ACC009 | → customer → branch | Lebanon |
| Accounts ACC005, ACC006 / ACC007, ACC008 | → customer → branch | Saudi Arabia / Qatar |
| Account ACC010 | customer C999 doesn't exist | Unknown |
| Loans L001-L009 / L010 | same as the matching customer / C999 | as customer / Unknown |
| Transactions T0001-T0004, T0009, T0011 | → ACC001-ACC004 | Lebanon |
| Transactions T0005, T0006, T0012-T0014 | → ACC005, ACC006 | Saudi Arabia |
| Transactions T0007, T0008, T0015 | → ACC007, ACC008 | Qatar |
| Transaction T0010 | account ACC999 doesn't exist | Unknown |
| Every capital_positions, liquidity_daily, fx_rates row | no branch | Group |

Every row in the sample: `source_system` = `CORE_CSV`, `source_file` = its CSV's name, and one
shared `ingest_batch_id`. Hand-computed, not verified by an actual run.

## 7. Open items

1. The real source names and their countries (question 7 for the bank in the backlog) replace the
   `CORE_CSV` placeholder: each source then gets its own landing folder and Notebook 1 run with
   `source_system` / `source_country` set.
2. `REGION_COUNTRY` is inferred from region names — confirm.
