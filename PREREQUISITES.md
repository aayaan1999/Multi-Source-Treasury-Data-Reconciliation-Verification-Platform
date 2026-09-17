# Prerequisites

Tech stack and access required to build and run this POC, based on `bank-x poc-brief.md`.

## Data Processing (Databricks side)

- **Databricks workspace** — runtime version to be confirmed with the client (brief section 11, Q1)
- **Apache Spark / PySpark** — all four notebooks are written in PySpark
- **Delta Lake** — required for every output table (`treasury_positions_raw`, `treasury_positions_clean`, `treasury_positions_exceptions`, `treasury_consolidated_report`, `exception_summary`); confirm with client whether it's already enabled on the workspace or needs setup (brief section 11, Q2)
- **CSV export capability** — Databricks output must be exportable to CSV for the Appian handoff

## Workflow & UI (Appian side)

- **Appian platform access** — for building the Exception Queue, Case Detail, Consolidated Report, and Audit Trail views
- **Appian connected system or file-drop mechanism** — to ingest Databricks CSV exports; exact mechanism still to be decided with the client (brief section 11, Q3-Q4)

## Input Data

- Three sample entity CSV files (not yet created): `lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv` — see brief section 4 for required schema and injected data-quality issues
- Hardcoded FX rate table (USD/SAR/QAR/LBP conversions) — simulated for POC, no live feed

## Dev Tooling

- **Git / GitHub** — this repo (`https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`), branch `main`
- **Claude Code** — used to generate the PySpark notebook code

## Open Questions Blocking Setup

These are listed in brief section 11 and should be resolved with the Dev Lead/client before Day 1 of the build:

1. Databricks runtime version available in the client's environment
2. Whether Delta Lake is already enabled or needs setup
3. Simplest Databricks → Appian integration mechanism (file drop, REST API, or connected system)
4. Whether Appian needs CSV or can read Delta tables directly
5. Any branding requirements for the Appian UI for the demo

---

## End-to-End Setup Process

This walks through standing up the full pipeline from an empty Databricks workspace through
to Appian consuming clean output. `notebooks/01_ingestion_standardisation.py` currently defaults
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
3. Enable **Unity Catalog** if available, so `treasury_positions_raw`, `treasury_positions_clean`, `treasury_positions_exceptions`, `treasury_consolidated_report`, and `exception_summary` are governed, three-level-namespace tables (`catalog.schema.table`) rather than legacy Hive metastore tables — cleaner for handing off to an Appian connected system later.
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
3. **Notebook 3 (Reconciliation)** reads only `treasury_positions_clean` (exceptions are excluded until a human resolves them in Appian) and produces the group-level `treasury_consolidated_report`.
4. **Notebook 4 (Exception Summary)** reads `treasury_positions_exceptions` and produces `exception_summary` — counts by entity/flag type, for the demo narrative ("which entity has the most issues, of what type").
5. Notebooks 3 and 4 also export their Delta table output to CSV in the `reports/`/`exceptions/` storage folders — this CSV is the file Appian actually reads.

An exception approved in Appian doesn't get looped back into `treasury_positions_clean` automatically for this POC — file-based, one-directional integration only (brief section 6, "no need for real-time API for POC").

### 6. Databricks Jobs (running notebooks 1-4 in sequence)

Once individual runs are validated manually, wire them into a **Databricks Job** (Workflows) with 4 sequential tasks (one per notebook) and a "run on new data arrival" or scheduled trigger — this is what would replace manually clicking "Run All" on each notebook in a live (non-demo) deployment. Not required for the 1-week POC demo itself, but worth setting up once notebooks are validated so the Day 7 rehearsal can show a live end-to-end run instead of pre-run output.

### 7. Connector: Databricks → Appian

Per brief section 6/11 (Q3-Q4), pick whichever is simplest for the client's Appian environment:

- **File drop (simplest for POC)** — Notebook 3/4's CSV export lands in a storage folder (or SFTP/network share) that an Appian process model polls or is triggered on, using Appian's **File System connected system** or a scheduled process.
- **Appian connected system reading Delta directly** — requires a JDBC/ODBC connection from Appian to Databricks SQL Warehouse (Databricks provides a JDBC driver); more setup, avoids the CSV intermediate step, but not necessary for a 1-week POC per the brief's own guidance ("file-based integration is sufficient").
- **REST API** — Databricks Jobs/SQL REST API could be called from an Appian integration, but the brief explicitly deprioritizes this for POC scope.
