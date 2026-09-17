# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project State

This repository currently contains only the POC brief (`bank-x poc-brief.md`). No code, notebooks, or sample data files exist yet — this is a planning document for a POC that has not been built. When asked to start implementation, treat the brief as the spec and check in on scope before generating large amounts of code.

## What This Project Is

A proof-of-concept for **Bank x** (Lebanon's largest regional bank, entities in Lebanon, France, Switzerland, Turkey, KSA, Qatar) to replace manual Excel-based Treasury reconciliation with an automated pipeline. The core pain point: the bank ingests quantitative financial position data from multiple entity source systems in inconsistent formats and must verify, reconcile, and consolidate it for BDL/CMA/BCC regulatory reporting.

The POC has two platform halves with a file-based (CSV) handoff between them — there is no live integration for this phase:

1. **Databricks (PySpark, Delta Lake)** — data ingestion, standardisation, data-quality verification, and reconciliation. This is the part Claude Code is expected to build.
2. **Appian** — exception management workflow (claim/approve/reject with mandatory comments), consolidated report view, and audit trail. Owned by a separate Appian developer; not Claude Code's responsibility unless asked.

## Databricks Build Scope (the part Claude Code owns)

Per the brief (`bank-x poc-brief.md` section 5), the deliverable is **four PySpark notebooks**, run in sequence, all using Delta Lake for output tables:

1. **Notebook 1 — Ingestion & Standardisation**
   - Read three entity CSVs (Lebanon, KSA, Qatar — different schemas/column names/date formats/currency notations per entity, see section 4 of the brief for exact per-entity quirks)
   - Standardise to a common schema: column names, `YYYY-MM-DD` dates, `XXX/YYY` currency pair notation, USD-equivalent amounts via a hardcoded FX rate table (no live feed for POC)
   - Output: `treasury_positions_raw`

2. **Notebook 2 — Data Quality Verification**
   - Flags each row per the checks in brief section 5 (`MISSING_DATE`, `MISSING_TRADER`, `INVALID_CCY_PAIR`, `INVALID_AMOUNT`, `RECONCILIATION_MISMATCH`, `LIMIT_BREACH`, `DUPLICATE_RECORD`, `CROSS_ENTITY_MISMATCH`)
   - Outputs: `treasury_positions_clean` (passing records), `treasury_positions_exceptions` (flagged, with flag label + description)

3. **Notebook 3 — Reconciliation & Consolidated Report**
   - Aggregates clean positions by entity/currency pair/position type into a group-level view
   - Flags currency pairs where group exposure exceeds a configurable limit
   - Output: `treasury_consolidated_report` (Delta table + CSV export for Appian/demo)

4. **Notebook 4 — Exception Summary Report**
   - Counts exceptions by type and entity
   - Output: `exception_summary` (Delta table + CSV export)

Notebooks run in this order since each depends on the previous one's output table. Downstream consumers (Appian) read CSV exports, not Delta tables directly, for this POC.

## Conventions When Building Notebooks

- Use PySpark + Delta Lake (`.format("delta")`) for all table outputs — this is an explicit requirement of the brief, not a default to reconsider.
- Include inline comments explaining each transformation step (the brief explicitly asks for this — an exception to the usual no-comments default, since these notebooks are handed to a Databricks developer unfamiliar with the code).
- Sample entity CSVs (`lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv`) are expected to exist before the notebooks can be validated — check whether the Dev Lead has produced them before assuming they're present. Each file deliberately contains injected data-quality issues (missing values, format mismatches, limit breaches, a duplicate, a cross-entity mismatch) that the verification notebook must catch.
