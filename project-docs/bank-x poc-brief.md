# POC Brief: Multi-Source Treasury Data Reconciliation & Verification Platform
**Client Context:** Bank x (Demo/POC — not a live client engagement yet)
**Prepared by:** Parth Gupta, CEO, Appbay Technologies
**Target Demo Date:** Within 1 week
**xence for this brief:** Dev Lead + Databricks Developer + Appian Developer

---

## 1. Background and Business Context

Bank x is Lebanon's largest regional bank with entities in:
- Lebanon (HQ)
- France
- Switzerland
- Turkey
- Sx Arabia (KSA)
- Qatar

The Head of Middle Office (our contact) leads Treasury compliance across all entities, covering:
- Liquidity positions
- FX open positions
- Money Market transactions
- Capital Markets exposures

**The core pain point stated by the client on the call:**

> "We receive quantitative financial data from different sources. The challenge is data verification, refinement, and consolidation across entities. We are heavily investing in solving this."

Since Lebanon's financial crisis began in 2019, this problem has become significantly worse because:
- Local data sources are inconsistent and often manually produced
- BDL (Banque du Liban) regulatory reporting requirements have increased dramatically
- Each entity produces data in different formats and systems
- Manual Excel-based reconciliation is the current approach
- Any data error creates regulatory risk under BDL, CMA, and BCC

---

## 2. Problem Statement

The Treasury Middle Office team at a multi-entity bank needs to:

1. **Ingest** financial position data from multiple entity source systems (different formats, different schemas, different currencies)
2. **Verify** data quality, flag missing values, outliers, format mismatches, and cross-entity inconsistencies
3. **Reconcile** positions across entities into a single consolidated group view
4. **Flag exceptions** where data fails verification for manual review and approval
5. **Produce** a clean, xtable consolidated report for regulatory submission and group risk oversight

**Currently:** This is done manually in Excel across multiple team members. It is slow, error-prone, and produces no xt trail.

---

## 3. Proposed POC Architecture

### Platform Split

| Layer | Platform | Owner |
|---|---|---|
| Data ingestion, cleaning, verification, reconciliation | Databricks | Databricks Developer + Claude Code |
| Exception management workflow, approval, xt trail | Appian | Appian Developer |
| Integration between layers | REST API / Databricks output to Appian | Both |

### High-Level Flow

```
[Source Files: Entity 1, 2, 3]
        ↓
[Databricks: Ingest & Standardise]
        ↓
[Databricks: Data Quality Checks & Verification]
        ↓
[Databricks: Reconciliation Logic]
        ↓
      ↙         ↘
[Clean Data]   [Exception Records]
[Output Report] [→ Appian Exception Workflow]
                        ↓
                [Manual Review & Approval]
                        ↓
                [xt Trail & Final Report]
```

---

## 4. Sample Data to Simulate (Dev Lead to Create)

Since we do not have real Bank x data, simulate three entity source files. Each file represents one entity's daily Treasury position report.

### File 1: Lebanon Entity — `lebanon_positions.csv`

| Column | Description | Sample Issues to Inject |
|---|---|---|
| trade_date | Date of position | Some rows missing |
| entity_code | LEB | Consistent |
| currency_pair | USD/LBP, EUR/USD, etc. | Some invalid codes |
| position_type | FX, MM, Liquidity | Some nulls |
| notional_amount | Numeric | Some as text strings |
| base_currency_amount | Numeric | Some negative where not expected |
| counter_currency_amount | Numeric | Some mismatched vs notional |
| trader_id | Staff ID | Some missing |
| limit_threshold | Approved limit | Some rows exceed limit |
| data_source | Core banking system name | Inconsistent naming |

### File 2: KSA Entity — `ksa_positions.csv`

Same columns but:
- Amounts in SAR instead of USD
- Date format different (DD/MM/YYYY vs YYYY-MM-DD)
- Some currency pairs use different naming convention (e.g. USDSAR vs USD/SAR)
- Some trader IDs in different format

### File 3: Qatar Entity — `qatar_positions.csv`

Same columns but:
- Amounts in QAR
- Some columns named slightly differently (e.g. `trade_amt` instead of `notional_amount`)
- A few rows with duplicate trade IDs

**Inject these specific data quality issues deliberately across the three files:**
- 3 to 5 missing values per file
- 2 to 3 format mismatches (dates, currency codes)
- 1 to 2 positions that breach the limit threshold
- 1 duplicate record
- 1 cross-entity inconsistency (same trade appearing in two entity files with different amounts)

---

## 5. Databricks Build Scope (Claude Code + Databricks Developer)

### Notebook 1: Data Ingestion and Standardisation
- Read all three CSV files
- Standardise column names to a common schema
- Standardise date formats to YYYY-MM-DD
- Standardise currency pair notation to XXX/YYY format
- Convert all amounts to USD equivalent using a hardcoded FX rate table (simulate, no live feed needed for POC)
- Add entity_code column if missing
- Output: single unified Delta table `treasury_positions_raw`

### Notebook 2: Data Quality Verification
Run these checks and flag each row with a status:

| Check | Flag Label |
|---|---|
| Missing trade_date | MISSING_DATE |
| Missing trader_id | MISSING_TRADER |
| Invalid currency pair format | INVALID_CCY_PAIR |
| Notional amount is non-numeric or zero | INVALID_AMOUNT |
| Counter amount does not reconcile to notional within tolerance | RECONCILIATION_MISMATCH |
| Position exceeds limit_threshold | LIMIT_BREACH |
| Duplicate trade_id within same entity | DUPLICATE_RECORD |
| Same trade_id across two entities with different amounts | CROSS_ENTITY_MISMATCH |

- Output clean records to: `treasury_positions_clean`
- Output flagged records to: `treasury_positions_exceptions` with flag label and description column

### Notebook 3: Reconciliation and Consolidated Report
- Aggregate clean positions by entity, currency pair, and position type
- Produce group-level consolidated view across all three entities
- Calculate total group FX exposure by currency pair
- Flag any currency pair where group-level exposure exceeds a configurable group limit
- Output: `treasury_consolidated_report` Delta table
- Export to CSV for Appian and for demo display

### Notebook 4: Exception Summary Report
- Count exceptions by type and entity
- Produce a summary table showing which entity has the most data quality issues and of what type
- Output: `exception_summary` table
- Export to CSV

---

## 6. Appian Build Scope (Appian Developer)

### What Appian needs to display and manage:

**View 1: Exception Queue**
- List all records from `treasury_positions_exceptions`
- Show: entity, trade date, currency pair, flag type, flag description, amount
- Allow Middle Office officer to claim a case

**View 2: Exception Case Detail**
- Show full record detail
- Allow officer to: Approve (override and include in consolidated report), Reject (exclude from report), Request more information
- Mandatory comment field before any action
- All actions logged with timestamp and user ID

**View 3: Consolidated Report View**
- Display `treasury_consolidated_report` output
- Show group exposure by currency pair
- Highlight any breaches in red
- Export to PDF button

**View 4: xt Trail**
- Every action taken on every exception logged with user, timestamp, action, comment
- Filterable by date, entity, user, action type

### Integration:
- Appian reads from Databricks output CSVs via connected system or file drop (whichever is simpler for POC)
- No need for real-time API for POC, file-based integration is sufficient

---

## 7. What Claude Code Will Handle

Hand Claude Code the following instructions:

**Prompt to give Claude Code:**

> "Build four Databricks notebooks in PySpark for a Treasury position reconciliation POC. The inputs are three CSV files representing FX and money market positions from three bank entities: Lebanon, KSA, and Qatar. Notebook 1 ingests and standardises all three files to a common schema. Notebook 2 runs data quality checks and flags exceptions with specific flag labels. Notebook 3 produces a consolidated group position report. Notebook 4 produces an exception summary. Use Delta Lake for all outputs. Include inline comments explaining each step. Output tables are: treasury_positions_raw, treasury_positions_clean, treasury_positions_exceptions, treasury_consolidated_report, exception_summary."

Claude Code will produce working PySpark notebook code. Your Databricks developer then:
- Reviews the logic
- Adjusts for your actual Databricks environment and cluster config
- Runs against the sample CSV files
- Validates the output tables

---

## 8. POC Deliverables for the Demo

| Deliverable | Owner | Status |
|---|---|---|
| Sample CSV files (3 entities with injected issues) | Dev Lead | To build |
| Databricks Notebook 1: Ingest and Standardise | Claude Code + Databricks Dev | To build |
| Databricks Notebook 2: Data Quality Checks | Claude Code + Databricks Dev | To build |
| Databricks Notebook 3: Consolidated Report | Claude Code + Databricks Dev | To build |
| Databricks Notebook 4: Exception Summary | Claude Code + Databricks Dev | To build |
| Appian Exception Queue view | Appian Dev | To build |
| Appian Case Detail and Approval workflow | Appian Dev | To build |
| Appian Consolidated Report view | Appian Dev | To build |
| Appian xt Trail view | Appian Dev | To build |
| Integration: Databricks output → Appian | Both | To build |

---

## 9. Demo Flow for Client (Reference for Dev Lead)

The demo will show Hana (Head of Middle Office, Bank x) the following story:

1. Show three entity source files with real-world data quality issues
2. Run Notebook 1 live or show pre-run output: "All three sources ingested and standardised into one schema"
3. Run Notebook 2 live or show pre-run output: "Data quality check complete, here are the exceptions flagged automatically"
4. Switch to Appian: "Your Middle Office officer sees the exception queue, opens a case, reviews the flagged record, approves or rejects it with a mandatory comment"
5. Show Consolidated Report view: "Once exceptions are resolved, here is the group position view across all three entities"
6. Show xt Trail: "Every decision is logged. BDL examiner asks what happened with this record on this date, here is the full trail"

**The key message to land:** Your team stops spending hours in Excel chasing data inconsistencies. The system finds them automatically, routes them for human decision, and keeps the xt trail without anyone having to reconstruct it.

---

## 10. Timeline Suggestion

| Day | Task |
|---|---|
| Day 1 | Dev lead creates sample CSV files. Claude Code generates all 4 notebook templates. |
| Day 2 | Databricks developer reviews and refines notebooks, runs against sample data |
| Day 3 | Databricks developer validates all output tables, fixes any issues |
| Day 4 | Appian developer builds Exception Queue and Case Detail views |
| Day 5 | Appian developer builds Consolidated Report and xt Trail views |
| Day 6 | Integration between Databricks outputs and Appian, end to end test |
| Day 7 | Full demo run-through, fix any issues, prepare demo environment |

---

## 11. Questions Dev Lead Should Answer Before Starting

1. What Databricks runtime version is available in our environment?
2. Is Delta Lake already enabled or does it need to be set up?
3. What is the simplest integration mechanism between Databricks output and Appian in our current setup, file drop, REST API, or connected system?
4. Does Appian dev need the Databricks output as CSV or can it read Delta tables directly?
5. Any branding requirements for the Appian UI for the demo?
