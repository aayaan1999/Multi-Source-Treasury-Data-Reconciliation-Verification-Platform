# Databricks Setup Walkthrough

Step-by-step setup for the Azure Databricks environment this POC runs on, against the **bank-wide
schema** (`customers`, `accounts`, `loans`, `transactions`, `branches`, `capital_positions`,
`liquidity_daily`, `fx_rates`). Companion to the higher-level "End-to-End Setup Process" section in
`PREREQUISITES.md` — this file is the click-by-click version.

**Conventions used throughout (and hardcoded in `notebooks/`):**

| Thing | Value |
|---|---|
| Catalog | `dbw_bankx_treasury_poc` (the workspace's existing catalog) |
| Schema | `raw` (all Bronze/Silver/Gold tables land here, bare table names) |
| Landing volume + folder | volume `raw`, folder `resources`: `/Volumes/dbw_bankx_treasury_poc/raw/raw/resources` |
| Sample data | `bank-data/*.csv` (8 files); a gitignored copy lives in `resources/bank-data-upload/` |

Every notebook starts with a cell running `USE CATALOG` / `USE SCHEMA` so bare table names resolve
the same way everywhere. If your catalog has a different name, change that cell in each notebook and
Notebook 1's `input_dir` default.

Two paths are documented:
- **Community Edition quick-start** (section 0) — free, but has no Unity Catalog, so paths differ.
- **Azure Databricks** (sections 1 onward) — paid, Unity Catalog + volumes + Repos.

---

## 0. Community Edition Quick-Start (free, no Azure account needed)

Fastest zero-cost way to prove the notebook logic. **Trade-off:** no Unity Catalog, no volumes, no
Repos — tables live in the default Hive metastore and notebooks must be uploaded manually.

- Sign up: https://community.cloud.databricks.com/
- Docs: https://docs.databricks.com/aws/en/getting-started/community-edition

Steps:
1. Sign up, then **Compute** → **Create Compute** (default single-node cluster).
2. **Data** → **Add Data** → **Upload File** → upload the 8 CSVs from `bank-data/`. They land under `/FileStore/tables/`.
3. **Workspace** → **Import** → upload `notebooks/01_...` through `06_...` and `fx_utils.py`.
4. In each notebook **delete the `USE CATALOG` / `USE SCHEMA` cell** (there is no Unity Catalog) and set Notebook 1's `input_dir` widget to `/FileStore/tables`.
5. Run in order (see section 9).

---

## Cost Notice: Sections 1-7 Are Paid Azure Services

Workspace, compute, storage and Access Connector are normal billed Azure resources. The Azure free
account's **$200 / 30-day credit** (https://azure.microsoft.com/en-us/free/) comfortably covers this
POC's tiny data. The only meaningful line item is **cluster runtime** — keep auto-terminate on.

| Resource (section) | What's billed |
|---|---|
| Databricks workspace (1) | Nothing by itself — cost is driven by compute |
| Compute (2) | Databricks DBUs + the underlying Azure VM, per hour running |
| Unity Catalog (3) | Free to create |
| ADLS Gen2 storage (4) | Capacity + transactions — negligible here |
| Access Connector (5) | Free |
| Databricks Repos (7) | Free |

---

## 1. Create the Azure Databricks workspace

- Portal: https://portal.azure.com/ · Create blade: https://portal.azure.com/#create/Microsoft.Databricks
- Docs: https://learn.microsoft.com/en-us/azure/databricks/getting-started/

1. **Create a resource** → "Azure Databricks" → **Create**
2. Resource group: e.g. `rg-bankx-treasury-poc`; workspace name: e.g. `dbw-bankx-treasury-poc`
3. Pricing tier: **Premium** (required for Unity Catalog)
4. **Review + create** → **Create** → **Launch Workspace**

---

## 2. Create compute

- Docs: https://learn.microsoft.com/en-us/azure/databricks/compute/configure

1. **Compute** → **Create compute**; access mode **Single user**
2. Runtime **13.3 LTS** or later; smallest node type; auto-terminate (e.g. 60 min idle)

Serverless compute also works — Databricks may add an `environment_version` header to notebooks
when you use it; that's harmless.

---

## 3. Catalog, schema and landing volume

Newer accounts have **Default Storage** enabled. On those, **`CREATE CATALOG` via SQL fails** with
`Metastore storage root URL does not exist`. Don't create a catalog in SQL — either use the
workspace's existing catalog (this project uses `dbw_bankx_treasury_poc`; find yours with
`SHOW CATALOGS;`) or create one in the **Catalog UI** (**+** → **Create a catalog** → Default Storage).

Then, in the SQL editor:
```sql
CREATE SCHEMA IF NOT EXISTS dbw_bankx_treasury_poc.raw;
CREATE VOLUME IF NOT EXISTS dbw_bankx_treasury_poc.raw.raw;
SHOW VOLUMES IN dbw_bankx_treasury_poc.raw;      -- expect: raw
```

**Volume paths need four parts:** `/Volumes/<catalog>/<schema>/<volume>/<file>`. A path like
`/Volumes/dbw_bankx_treasury_poc/raw` with no volume segment makes Databricks parse the file name as
the volume name and fail with `UC_VOLUME_NOT_FOUND ... Volume 'x'.'raw'.'customers.csv' does not exist`.

- Docs — Unity Catalog: https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started
- Account console (metastore admin): https://accounts.azuredatabricks.net/

---

## 4. (Optional) ADLS Gen2 external storage

Only needed if you want storage you control instead of Default Storage. Skip for the POC.

- Portal: https://portal.azure.com/#create/Microsoft.StorageAccount
- Docs: https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction

1. **Storage account** in the same resource group; **Advanced** → enable **hierarchical namespace**
2. Create a container (e.g. `bankx-poc`)

---

## 5. (Optional) Connect Databricks to that storage

Only if you did section 4. Create an **Access Connector for Azure Databricks**, grant it
**Storage Blob Data Contributor** on the storage account, add it as a storage credential and
external location in Databricks, then create the catalog with `MANAGED LOCATION '<abfss path>'`.

- Docs: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/storage-credentials
- Docs: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/external-locations

---

## 6. Upload the sample data

Upload the 8 CSVs from `bank-data/` (or the gitignored copy in `resources/bank-data-upload/`):
`customers`, `accounts`, `loans`, `transactions`, `branches`, `capital_positions`,
`liquidity_daily`, `fx_rates`.

- **UI:** **Catalog** → `dbw_bankx_treasury_poc` → `raw` → **Volumes** → `raw`, create a folder named `resources` inside it, open it → **Upload to this volume**. Files go directly in `resources/`, not in a further subfolder.
- **CLI:** `databricks fs cp bank-data/customers.csv dbfs:/Volumes/dbw_bankx_treasury_poc/raw/raw/resources/customers.csv` (repeat per file)

Verify:
```sql
LIST '/Volumes/dbw_bankx_treasury_poc/raw/raw/resources';   -- expect 8 files
```

- Docs: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/volumes

---

## 7. Connect this GitHub repo via Databricks Repos

- Docs: https://learn.microsoft.com/en-us/azure/databricks/repos/
- Repo: https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform

1. Link GitHub: user icon → **Settings** → **Linked Accounts** → **Git integration** → GitHub → personal access token with `repo` scope (https://github.com/settings/tokens)
2. **Repos** (sidebar) → **Add Repo** → paste the repo URL → **Create Repo**
3. Work **inside the Repo folder** so edits can sync back.

**Two-way sync:**
- **Databricks → GitHub:** in the Repo, open the **Git** dialog, enter a message, **Commit & Push**. Pull first if GitHub has newer commits.
- **GitHub → Databricks:** **Git** → **Pull**, or use the automated workflow below.
- Don't edit the same notebook in both places at once. After pushing from Databricks, `git pull` locally.

### 7a. Automate the pull (optional — `.github/workflows/databricks-sync.yml`)

Repos never pulls on its own. The workflow calls the Databricks REST API to pull the Repo after every
push to `main`. **One-way only** (GitHub → Databricks); it never pushes Databricks edits back.

- Docs: https://learn.microsoft.com/en-us/azure/databricks/api/workspace/repos/update
- PATs: https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/pat
- Secrets: https://docs.github.com/en/actions/security-guides/encrypted-secrets

Setup (one-time):
1. **Databricks PAT:** user icon → **Settings** → **Developer** → **Access tokens** → **Generate new token** (shown once).
2. **Repo ID — do not read it off the browser URL.** The `/browse/folders/<id>` value is not the Repo's API ID. Use:
   ```
   curl -s -H "Authorization: Bearer <PAT>" "https://<workspace-host>/api/2.0/repos" | python3 -m json.tool
   ```
   or `databricks repos list`, and take the `id` of the entry whose `path` matches this repo.
3. **Three GitHub Actions secrets** (repo → **Settings** → **Secrets and variables** → **Actions**):
   - `DATABRICKS_HOST` — workspace URL, no trailing slash (e.g. `https://adb-xxxx.xx.azuredatabricks.net`)
   - `DATABRICKS_TOKEN` — the PAT, no quotes or spaces
   - `DATABRICKS_REPO_ID` — the numeric API `id`
4. Push to `main`; check **Actions** → "Sync Databricks Repo".

Treat the PAT like a password; rotate it if exposed.

#### Troubleshooting: curl exit code 22 / workflow fails

`curl -f` turns any 4xx/5xx into a bare exit 22; the workflow prints the HTTP status and body in its
log, so read that first. Likely causes, in order: trailing slash on `DATABRICKS_HOST` (404); wrong
Repo ID (404 / "repo does not exist"); bad or expired token (401/403).

---

## 8. Notebook order and what each one needs

All notebooks use bare table names in `dbw_bankx_treasury_poc.raw` (set by their first cell).

| # | Notebook | Reads | Writes | Layer |
|---|---|---|---|---|
| 1 | `01_ingestion_standardisation` | the 8 CSVs in `raw/raw/resources` | `raw_*` (8 tables) | Bronze |
| 2 | `02_data_quality_verification` | `raw_*` | `*_clean` (8), `data_quality_exceptions` | Silver |
| 3 | `03_kpi_summary` | `*_clean` | `kpi_daily_summary` | Gold |
| 4 | `04_exception_summary` | `data_quality_exceptions`, `raw_*` | `exception_summary_by_table`, `exception_summary_by_flag` | Gold |
| 5 | `05_fraud_business_rules` | `transactions_clean` | `flagged_transactions` | Silver → Gold |
| 6 | `06_portfolio_branch_scenario_snapshot` | `*_clean` | 9 portfolio/branch/scenario tables | Gold |

Run 1 → 2 first; then 3, 4, 5, 6 in any order. Notebooks 3, 5 and 6 `%run ./fx_utils`, which calls a
live FX API — the cluster needs outbound internet, and it writes `fx_rate_usage_log`. The
`multi_source_*` notebooks each need external credentials stored as **Databricks secrets**, not
hardcoded.

---

## 9. First run and verification

1. Open `notebooks/01_ingestion_standardisation.py` in the Repo and attach it to compute.
2. Set the `input_dir` widget to `/Volumes/dbw_bankx_treasury_poc/raw/raw/resources` (an existing widget value overrides the notebook default, so check it).
3. **Run All**, then verify:
   ```sql
   SHOW TABLES IN dbw_bankx_treasury_poc.raw;                    -- 8 raw_* tables
   SELECT COUNT(*) FROM dbw_bankx_treasury_poc.raw.raw_customers;
   ```
   Row counts should match the CSVs (header excluded), and the blank `amount` in
   `transactions.csv` should be `NULL`, not an error.
4. Continue with Notebooks 2-6, checking each output against the traceability table in its spec
   under `specs/`. Flip that spec's "not run against a live cluster" note once it passes.

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `UC_VOLUME_NOT_FOUND ... 'customers.csv'` | `input_dir` missing the volume segment | Use the full `/Volumes/<catalog>/<schema>/<volume>` path |
| `Metastore storage root URL does not exist` on `CREATE CATALOG` | Default Storage is enabled | Use an existing catalog or create one in the Catalog UI |
| `NO_SUCH_CATALOG_EXCEPTION` | Catalog name in the notebooks doesn't exist | `SHOW CATALOGS;` and update the `USE CATALOG` cell |
| Tables land in an unexpected schema | The `USE CATALOG`/`USE SCHEMA` cell was removed or not run | Restore the first code cell of the notebook |

---

## 10. Pipeline job and Neon Postgres

Full design and acceptance checks: `specs/pipeline-job-and-neon-load.md`. Steps:

1. **Neon:** create a free project + database at https://neon.tech and copy the connection details.
2. **Create the tables in Neon** (from your laptop, in the repo root):
   ```
   pip install psycopg2-binary
   $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"   # PowerShell
   python db/apply_schema.py
   ```
3. **Store the Neon credentials as Databricks secrets** (never in code):
   ```
   databricks secrets create-scope neon
   databricks secrets put-secret neon host --string-value <neon host>
   databricks secrets put-secret neon database --string-value <db name>
   databricks secrets put-secret neon user --string-value <user>
   databricks secrets put-secret neon password --string-value <password>
   ```
4. **Deploy the job:** `databricks bundle validate`, then `databricks bundle deploy` (needs the Databricks CLI
   authenticated to the workspace: `databricks auth login --host <workspace url>`).
5. **Trigger it:** upload the 8 CSVs to the landing folder. The job (Workflows → `bank-data-pipeline`) starts after
   the folder has been quiet for 2 minutes. To run it manually, click **Run now**.

---

## Reference: link list

| Purpose | Link |
|---|---|
| Databricks Community Edition | https://community.cloud.databricks.com/ |
| Azure Portal | https://portal.azure.com/ |
| Create Azure Databricks resource | https://portal.azure.com/#create/Microsoft.Databricks |
| Databricks account console | https://accounts.azuredatabricks.net/ |
| Compute configuration docs | https://learn.microsoft.com/en-us/azure/databricks/compute/configure |
| Unity Catalog docs | https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started |
| Volumes docs | https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/volumes |
| Repos / Git integration docs | https://learn.microsoft.com/en-us/azure/databricks/repos/ |
| GitHub personal access tokens | https://github.com/settings/tokens |
| This project's repo | https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform |
