# Prerequisites

Tech stack and access required to build and run this platform. `Middle East bank data cleaning
and reporting.md` is the source of truth for everything, including the Databricks layer as of the
Notebook 1-2 rewrite. `bank-x poc-brief.md` is historical reference only — see `CLAUDE.md`.

## Data Processing (Databricks side)

- **Databricks workspace** — runtime version to be confirmed with the client
- **Apache Spark / PySpark** — all four notebooks are written in PySpark
- **Delta Lake** — required for every output table (`raw_customers`, `raw_accounts`, `raw_loans`,
  `raw_transactions`, `raw_branches`, `raw_capital_positions`, `raw_liquidity_daily`, `raw_fx_rates`
  from Notebook 1; `{table}_clean` × 8 and `data_quality_exceptions` from Notebook 2); confirm
  with client whether it's already enabled on the workspace or needs setup
- **CSV export capability** — Databricks output must be exportable to CSV for the application-layer import job

## Ingestion Layer (new — real-time FX + multi-source, MVP scope)

- **A live FX rate API account** (ExchangeRate-API or Open Exchange Rates are the leading
  candidates — confirm the chosen provider actually covers USD/EUR/LBP/SAR/QAR before committing;
  free ECB-only feeds like Frankfurter don't cover LBP/QAR) — see `specs/fx-realtime-ingestion.md`.
  **Called inline by Notebook 3/6's conversion logic at run time — not a scheduled polling job,
  not a source table.** No separate Databricks Job needed for this.
- **5 free cloud accounts** for multi-source ingestion (no ADF needed for this MVP — see
  `specs/multi-source-ingestion-adf.md`): **Neon** (Postgres), **Mockaroo** (mock API),
  **IMF Data API** (free, no key), **Salesforce Developer Edition** (free CRM), **Google Sheets**
  (+ a Google service account for API access)

## Application Layer (replaces the original Appian scope)

- **PostgreSQL** — full schema per the source doc: entity tables (`customers`, `accounts`, `loans`,
  `branches`), time-series tables (`transactions`, `capital_positions`, `liquidity_daily`, `fx_rates`),
  and reporting/workflow tables (`report_definitions`, `report_instances`, `report_line_items`,
  `validation_rules`, `calculation_audit`, `risk_weights`, `submitted_files`, `users`, `roles`,
  `workflow_steps`, `workflow_instances`, `tasks`, `comments`, `audit_log`, `limits`, `breaches`).
  Row-level security is used to enforce who sees what.
- **FastAPI** (Python) — backend/API layer
- **React + Tailwind CSS + Recharts** — frontend, six screens
- **APScheduler** — nightly batch jobs (Databricks CSV import, summary-table precomputation, breach
  detection); Celery + Redis only if this needs to scale past POC
- **ReportLab** — PDF export (regulatory report format)
- **openpyxl** — Excel export (regulator template layout)
- **Auth** — four seeded demo users (analyst, reviewer, approver, admin) is sufficient for the POC;
  Keycloak only if real SSO is required later
- **Dashboards stay custom React + Recharts, not Power BI/Tableau** — explicit decision (see
  `CLAUDE.md`); a BI tool would be faster for the pure-reporting screens but breaks the "one
  product" cohesion and can't do Screen 4's sub-second client-side recompute or Screen 6's
  write-actions, which are needed regardless

## Workflow Engine: Camunda 8 (self-hosted) — for the 3-week POC extension only

Overrides the source doc's original "don't use a workflow engine for the POC" guidance — see
`CLAUDE.md`'s "Workflow Engine Decision" and `3-WEEK-POC-PLAN.md`.

- **Zeebe** — the Camunda 8 process engine/broker
- **Elasticsearch** — required dependency for Operate
- **Operate** — process/incident monitoring (dev/debugging use, not necessarily demoed)
- **Tasklist** — human task UI + REST API; React's Screen 6 calls this instead of a custom
  FastAPI workflow endpoint
- **Docker Compose** (or the "Camunda 8 Run" self-managed bundle) — to stand up the above locally;
  budget real setup time for this (see `specs/camunda-bpmn-process-design.md` section 2)
- A small **bridge worker** (Python, Zeebe client SDK) — polls Postgres for newly-synced flagged
  records and starts a Camunda process instance per one; this is bespoke code, not an
  off-the-shelf Camunda Connector
- **Not included**: Camunda Identity/Keycloak auth (seeded users are enough for the POC), Optimize
  (redundant with the React Executive Summary screen), the Connectors runtime (overkill for one
  specific integration)

## Input Data

- Eight bank-wide sample CSVs (built, `bank-data/`): `customers.csv`, `accounts.csv`, `loans.csv`,
  `transactions.csv`, `branches.csv`, `capital_positions.csv`, `liquidity_daily.csv`,
  `fx_rates.csv` — small, hand-built (6-10 rows/table) with injected data-quality issues; see
  `specs/notebook-02-bank-data-quality.md` section 7 for what's in each
- **Historical, no longer consumed by any notebook:** `lebanon_positions.csv`, `ksa_positions.csv`,
  `qatar_positions.csv` (the original treasury-entity CSVs)
- **Not yet available at realistic scale**: the `bank-data/` CSVs above are notebook-testing size
  only — a proper synthetic data generator (the source doc references "two million transactions"
  as a performance-proofing case) is still needed before Screens 1, 2, 4, 5 can be built and
  demoed meaningfully (see `PLATFORM-BUILD-PLAN.md` Phase 1)

## Dev Tooling

- **Git / GitHub** — this repo (`https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`), branch `main`
- **Claude Code** — used to generate the PySpark notebooks and the FastAPI/React application code

## Open Questions Blocking Setup

1. Databricks runtime version available in the client's environment
2. Whether Delta Lake is already enabled or needs setup
3. Hosting target for PostgreSQL/FastAPI/React (Azure App Service, AKS, or local/dev for the demo) — not yet decided
4. Does real customer/loan/account/branch data exist anywhere, or does the full platform demo run entirely on synthetic data?
5. What scale should the synthetic dataset target — the source doc references "two million transactions" as a performance-proofing case; confirm whether the demo actually needs that scale
6. Which regulatory report template(s) are needed first for Screen 3 (capital adequacy is the one worked out in the source doc; others may need their own layout)
7. Any branding requirements for the React frontend for the demo
8. What file format(s) do the real source systems (core banking, loan systems, branch systems)
   actually export in? The current pipeline (Notebook 1) reads CSV directly — Spark also reads
   JSON/Parquet/Avro natively and Excel with an added library (`com.crealytics:spark-excel`), so
   any of those are a straightforward swap. **PDF or scanned-image exports are not** — those need
   a table-extraction/OCR preprocessing step *before* Notebook 1 can ingest anything, which is
   extra scope not currently accounted for anywhere in this plan. Confirm this before assuming
   any new entity/source system slots into the existing pipeline unchanged.
9. Which FX rate API to commit to (`specs/fx-realtime-ingestion.md`) — needs confirmed
   USD/EUR/LBP/SAR/QAR coverage, not just "many currencies supported"
10. What are the real ERP/CRM/external-banking source systems this platform will eventually
    connect to, and what are their actual transaction codes? `transaction_code_mapping`
    (`specs/multi-source-ingestion-adf.md` section 6) can't be populated without this — it's a
    hard blocker, not something resolvable with a placeholder assumption

---

## End-to-End Setup Process (Databricks portion)

This walks through standing up the Databricks side of the pipeline, from an empty workspace
through to CSV output ready for the PostgreSQL import job (`PLATFORM-BUILD-PLAN.md` Phase 1).
`notebooks/01_ingestion_standardisation.py` currently defaults
its `input_dir` widget to `/Volumes/treasury_poc/raw` — the storage setup below is what makes
that path real.

For the click-by-click version of steps 1-4 below, with direct links to every Azure Portal blade
and Databricks doc page used, see `DATABRICKS-SETUP.md`.

### 1. Azure Storage (raw file landing zone)

The three entity CSVs need somewhere the Databricks cluster can read from. For an Azure-hosted
workspace, that's **Azure Data Lake Storage Gen2 (ADLS Gen2)**:

1. Create (or reuse) a storage account with **hierarchical namespace enabled** (this is what makes it ADLS Gen2, not plain Blob Storage).
2. Create a container, e.g. `treasury-poc`, with folders `raw/`, `clean/`, `exceptions/`, `reports/` — mirrors the notebook stages.
3. Upload `lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv` into `raw/`.
4. Decide the connector (see section 3 below) before deciding whether Databricks reads this via a mounted path, a Unity Catalog external location, or direct `abfss://` URIs — this determines what `input_dir` should actually be set to.

### 2. Databricks Workspace Setup

1. Provision the Azure Databricks workspace (Premium tier if Unity Catalog governance is needed for the client's compliance requirements — likely relevant given BDL/CMA/BCC regulatory context).
2. Create a cluster (or use Serverless SQL/Jobs compute) with a Databricks Runtime version that includes Delta Lake by default (Runtime 10.4 LTS or later — bundled, no separate install) — confirms/resolves brief Q1-Q2.
3. Enable **Unity Catalog** if available, so `treasury_positions_raw`, `treasury_positions_clean`, `treasury_positions_exceptions`, `treasury_consolidated_report`, and `exception_summary` are governed, three-level-namespace tables (`catalog.schema.table`) rather than legacy Hive metastore tables — cleaner for the PostgreSQL import job to read from later.
4. Connect this GitHub repo via **Repos** (Workspace → Repos → clone `https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`) so the four notebooks sync directly instead of being manually copy-pasted — see prior discussion on notebook deployment.

### 3. Connector: Databricks ↔ Azure Storage

Pick one, in order of setup simplicity vs. production-readiness:

- **Unity Catalog external location + storage credential** (recommended if Unity Catalog is enabled) — register the ADLS container as an external location backed by a **managed identity** or **service principal**, then read/write via `abfss://` paths or, better, mount it as a **Databricks Volume** (`/Volumes/treasury_poc/raw`) so notebook code stays cloud-agnostic. This is the path the notebooks are already written against.
- **Cluster-scoped mount (`dbutils.fs.mount`)** — legacy approach using a service principal + OAuth or storage account access key stored in an Azure Key Vault-backed Databricks secret scope. Works without Unity Catalog but is being phased out by Databricks.
- **Direct `abfss://` access with SAS token / access key** — simplest for a throwaway POC, least secure; fine only if this never touches real client data.

Either way, the credential (service principal client secret, or storage account key) belongs in a **Databricks secret scope**, never hardcoded in a notebook.

### 4. Feeding Data In

1. Upload the sample CSVs to `raw/` in the storage container (manually for POC; a real deployment would have each entity's source system push files there on a schedule, or land them via an Azure Data Factory / Databricks Auto Loader pipeline).
2. Point Notebook 1's `input_dir` widget at the real path (`/Volumes/treasury_poc/raw` if using a Volume, or the `abfss://…` URI otherwise).
3. Run Notebook 1 — this is the only notebook that touches raw storage directly; everything downstream reads/writes Delta tables inside the workspace.

### 5. How the Cleaning/Verification Actually Runs

The four notebooks execute in strict sequence — each depends on the previous notebook's Delta table output:

1. **Notebook 1 (Ingestion & Standardisation)** reads the raw CSVs from storage, fixes schema/date/currency-pair inconsistencies, converts amounts to USD, writes `treasury_positions_raw`. Nothing is dropped here — malformed data is normalized where possible and passed through for verification, not silently discarded.
2. **Notebook 2 (Data Quality Verification)** reads `treasury_positions_raw`, runs the 8 checks from brief section 5 against every row, and splits the table in two: rows that pass everything go to `treasury_positions_clean`; anything that fails one or more checks goes to `treasury_positions_exceptions` with a flag label and description.
3. **Notebook 3 (Reconciliation)** reads only `treasury_positions_clean` (exceptions are excluded until a human resolves them in the application layer's Screen 6 workflow) and produces the group-level `treasury_consolidated_report`.
4. **Notebook 4 (Exception Summary)** reads `treasury_positions_exceptions` and produces `exception_summary` — counts by entity/flag type, for the demo narrative ("which entity has the most issues, of what type").
5. Notebooks 3 and 4 also export their Delta table output to CSV in the `reports/`/`exceptions/` storage folders — this CSV is what the nightly PostgreSQL import job (`PLATFORM-BUILD-PLAN.md` Phase 1) reads.

An exception approved in the application layer doesn't get looped back into `treasury_positions_clean` automatically for this POC — file-based, one-directional integration only, same philosophy as the original brief's "no need for real-time API for POC" guidance.

### 6. Databricks Jobs (running notebooks 1-4 in sequence)

Once individual runs are validated manually, wire them into a **Databricks Job** (Workflows) with 4 sequential tasks (one per notebook) and a "run on new data arrival" or scheduled trigger — this is what would replace manually clicking "Run All" on each notebook in a live (non-demo) deployment. Not required for the 1-week POC demo itself, but worth setting up once notebooks are validated so the Day 7 rehearsal can show a live end-to-end run instead of pre-run output.

### 7. Connector: Databricks → PostgreSQL (application layer)

Pick whichever is simplest to stand up first; either works for a POC:

- **File-based import job (simplest, matches original brief's philosophy)** — Notebook 3/4's CSV
  export lands in a storage folder; an APScheduler job (or a simple Python script run nightly)
  reads the CSVs and upserts into the corresponding PostgreSQL tables (`treasury_consolidated_report`,
  `exception_summary`, `treasury_positions_exceptions`).
- **Direct read via Databricks SQL Warehouse (JDBC/ODBC)** — the FastAPI import job connects
  straight to Databricks instead of reading CSV, avoiding the file intermediate step; more setup,
  not necessary for the POC.
- **REST API** — Databricks Jobs/SQL REST API could be called from the FastAPI backend, but adds
  complexity with no POC-stage benefit over the file-based approach.
