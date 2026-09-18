# Databricks Setup Walkthrough

Step-by-step setup for the Azure Databricks environment this POC runs on, with direct links to
the portals/docs used at each step. Companion to the higher-level "End-to-End Setup Process"
section in `PREREQUISITES.md` — this file is the click-by-click version.

Two paths are documented:
- **Community Edition quick-start** (below) — free, zero Azure setup, good enough to validate the
  notebook logic against the small sample CSVs (10-11 rows each).
- **Full Azure setup** (section 1 onward) — paid, Unity Catalog + ADLS Gen2 + Repos, needed once
  you're past validating logic and into the real PostgreSQL import integration.

---

## 0. Community Edition Quick-Start (free, no Azure account needed)

Fastest, zero-cost way to prove Notebooks 1-4 work before investing in the full Azure setup below.
**Trade-off:** no Unity Catalog, no ADLS Gen2, no Repos — Delta tables live in the workspace's
default (Hive) metastore instead of a governed catalog, and notebooks have to be uploaded manually
since Git integration isn't available on Community Edition.

- Sign up: https://community.cloud.databricks.com/
- Docs — Community Edition overview: https://docs.databricks.com/aws/en/getting-started/community-edition

Steps:
1. Go to https://community.cloud.databricks.com/ and sign up (email + password, no Azure/AWS account required)
2. Once logged in, **Compute** (left sidebar) → **Create Compute** → accept the default single-node cluster (Community Edition caps you to one small cluster with a 6-hour auto-terminate — fine for this data size)
3. **Data** (left sidebar) → **Add Data** → **Upload File** → upload `lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv` from this repo — Community Edition stores them under DBFS at a path like `/FileStore/tables/lebanon_positions.csv`
4. **Workspace** (left sidebar) → **Import** → upload `notebooks/01_ingestion_standardisation.py` directly from this repo (drag-and-drop or browse) — since there's no Repos/Git integration here, re-upload the file manually each time it changes
5. Open the imported notebook, attach it to the cluster from step 2
6. Since there's no Unity Catalog Volume here, set the `input_dir` widget to the DBFS path from step 3, e.g. `/FileStore/tables` — the notebook's `SOURCE_FILES` dict then resolves to `/FileStore/tables/lebanon_positions.csv` etc.
7. Also change the `OUTPUT_TABLE` write to the default Hive metastore (drop the three-level Unity Catalog namespace — `treasury_positions_raw` as a bare table name works as-is against Community Edition's default metastore)
8. **Run All** — confirms the same row-count sanity check as the full setup, at zero cost

When ready to move past logic validation (real storage, governed tables, CI-style Git sync, application-layer integration), continue with the full Azure setup starting at section 1 below.

---

## Cost Notice: Sections 1-7 Are Paid Azure Services

Everything from here on (workspace, compute, storage, Access Connector) is a normal billed Azure
resource — none of it is free-tier by default. It can be covered by the Azure free account's
**$200 / 30-day credit** (https://azure.microsoft.com/en-us/free/, requires a card at signup for
identity verification — no charge unless you exceed the credit or explicitly upgrade to
pay-as-you-go afterward). Given this POC's tiny data size, staying within $200 for a 1-week build
is very unlikely to be an issue, but keep auto-terminate on the cluster (step 2) so nothing burns
credit sitting idle. What actually generates cost:

| Resource (section) | What's billed |
|---|---|
| Databricks workspace (1) | Nothing by itself — cost is driven by compute usage, not the workspace resource |
| Compute cluster (2) | **Databricks DBUs** (Premium tier rate) + the underlying **Azure VM** it runs on, billed per hour while running |
| Unity Catalog metastore (3) | Free to create; no separate charge |
| ADLS Gen2 storage account (4) | Storage capacity + transactions — negligible at this data size (a few KB of CSVs) |
| Access Connector (5) | Free — it's just a managed identity, no compute of its own |
| Databricks Repos (7) | Free — no additional charge for Git integration |

So in practice: the only meaningful line item is **cluster runtime** (step 2) — stop/auto-terminate
it when not actively running notebooks, and the $200 credit comfortably covers a week of POC work.

---

## 1. Create the Azure Databricks workspace

- Azure Portal: https://portal.azure.com/
- Databricks resource creation blade (search "Azure Databricks" from the portal home, or go directly to): https://portal.azure.com/#create/Microsoft.Databricks
- Docs — workspace creation walkthrough: https://learn.microsoft.com/en-us/azure/databricks/getting-started/

Steps:
1. **Create a resource** → search "Azure Databricks" → **Create**
2. Resource group: new, e.g. `rg-bankx-treasury-poc`
3. Workspace name: e.g. `dbw-bankx-treasury-poc`
4. Pricing tier: **Premium** (required for Unity Catalog)
5. **Review + create** → **Create**
6. Once deployed → **Launch Workspace**

---

## 2. Create compute

- Docs — compute configuration: https://learn.microsoft.com/en-us/azure/databricks/compute/configure

Steps (inside the workspace UI, left sidebar → **Compute**):
1. **Create compute**
2. Access mode: **Single user** (simplest for a POC)
3. Databricks Runtime: **13.3 LTS** or later (Delta Lake included by default)
4. Node type: smallest available (`Standard_DS3_v2` or similar) — data volume here is tiny
5. Enable auto-termination (e.g. 60 minutes idle)
6. **Create compute**

---

## 3. Set up Unity Catalog

- Databricks account console (separate login from the workspace, org/account-admin level): https://accounts.azuredatabricks.net/
- Docs — Unity Catalog setup: https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started
- Docs — creating a metastore: https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/create-metastore

Steps:
1. In the account console → **Catalog** → create a metastore for your region if none exists yet, and assign it to your workspace
2. Back in the workspace UI → **Catalog** (left sidebar) → **Create Catalog** → name it `treasury_poc`
3. Inside the catalog → **Create Schema** → name it `raw` (or similar) — output tables will live at `treasury_poc.raw.treasury_positions_raw`, etc.

---

## 4. Set up Azure Data Lake Storage Gen2 (ADLS Gen2)

- Azure Portal — storage account creation: https://portal.azure.com/#create/Microsoft.StorageAccount
- Docs — ADLS Gen2 overview: https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction

Steps:
1. **Create a resource** → **Storage account** → same resource group as the Databricks workspace
2. **Advanced** tab → check **Enable hierarchical namespace** (this is what makes it ADLS Gen2, not plain Blob Storage)
3. **Review + create** → **Create**
4. Once created → **Containers** → **+ Container** → name it `treasury-poc`
5. Inside the container, create folders `raw/`, `clean/`, `exceptions/`, `reports/` (folders can be created implicitly on upload, or via **Storage Browser** → **Add Directory**)

---

## 5. Connect Databricks to the storage account (Unity Catalog external location)

- Docs — creating an Access Connector for Azure Databricks: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/storage-credentials
- Docs — creating external locations: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/external-locations
- Azure Portal — Access Connector resource creation: https://portal.azure.com/#create/Microsoft.AccessConnector

Steps:
1. Azure Portal → create an **Access Connector for Azure Databricks** resource (same resource group)
2. On the storage account → **Access Control (IAM)** → **Add role assignment** → role: **Storage Blob Data Contributor** → assign to the Access Connector's managed identity
3. In the Databricks workspace → **Catalog** → **External Data** → **Credentials** → **Create Credential** → type: Azure Managed Identity → point at the Access Connector from step 1
4. **Catalog** → **External Data** → **External Locations** → **Create Location** → URL: `abfss://treasury-poc@<storageaccountname>.dfs.core.windows.net/` → credential: the one just created
5. **Catalog** → your `treasury_poc.raw` schema → **Create** → **Volume** → name it `raw`, backed by the external location above (or a subpath of it). This produces the path `/Volumes/treasury_poc/raw/raw` (or similar) that notebook code reads from — matches the `input_dir` widget default pattern in `notebooks/01_ingestion_standardisation.py`.

---

## 6. Upload the sample data

- Docs — uploading files to a Volume: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/volumes
- Docs — Databricks CLI install/config: https://learn.microsoft.com/en-us/azure/databricks/dev-tools/cli/

Two options:
- **UI**: Catalog → navigate to the Volume created in step 5 → **Upload to this volume** → select `lebanon_positions.csv`, `ksa_positions.csv`, `qatar_positions.csv` from this repo
- **CLI**: install the Databricks CLI, run `databricks configure` to authenticate, then:
  ```
  databricks fs cp lebanon_positions.csv dbfs:/Volumes/treasury_poc/raw/raw/lebanon_positions.csv
  databricks fs cp ksa_positions.csv dbfs:/Volumes/treasury_poc/raw/raw/ksa_positions.csv
  databricks fs cp qatar_positions.csv dbfs:/Volumes/treasury_poc/raw/raw/qatar_positions.csv
  ```

---

## 7. Connect this GitHub repo via Databricks Repos

- Docs — Git integration with Databricks Repos: https://learn.microsoft.com/en-us/azure/databricks/repos/
- This repo: https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform

Steps:
1. In the workspace, first link your GitHub account: **Settings** (user icon, top right) → **Linked Accounts** → **Git integration** → provider: GitHub → add a GitHub personal access token (create one at https://github.com/settings/tokens with `repo` scope) or use OAuth if your org has the GitHub App installed
2. Left sidebar → **Repos** → **Add Repo**
3. Git repository URL: `https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`
4. **Create Repo** — the `notebooks/` folder appears, and `01_ingestion_standardisation.py` opens as a native Databricks notebook
5. To pull future updates pushed from this repo: open the Repo in the workspace → **Git** (branch icon) → **Pull**

### 7a. Automate the pull (optional — `.github/workflows/databricks-sync.yml`)

Databricks Repos never pulls automatically on its own — the manual "Pull" click in step 5 above
is the default. `.github/workflows/databricks-sync.yml` in this repo automates it: a GitHub
Actions workflow that calls the Databricks REST API to pull the Repo immediately after every push
to `main`.

- Docs — Repos API reference (the `PATCH /api/2.0/repos/{id}` call the workflow uses): https://learn.microsoft.com/en-us/azure/databricks/api/workspace/repos/update
- Docs — Databricks personal access tokens: https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/pat
- GitHub Actions secrets: https://docs.github.com/en/actions/security-guides/encrypted-secrets

Setup (one-time):
1. **Get a Databricks PAT**: workspace → user icon (top right) → **Settings** → **Developer** →
   **Access tokens** → **Generate new token**. Copy it immediately — it's shown only once.
2. **Get the Repo ID — do not read this off the browser URL.** The Databricks workspace UI now
   shows Repos/Git folders under a `/browse/folders/<folder_id>` path, and that folder ID is
   **not** the same as the Repo's API ID — using it is a common cause of this API call failing.
   Get the real ID from the API/CLI instead:
   ```
   curl -s -H "Authorization: Bearer <your PAT>" "https://<your-workspace-host>/api/2.0/repos" | python3 -m json.tool
   ```
   or, with the Databricks CLI: `databricks repos list`. Find the entry whose `path` matches this
   repo (e.g. `/Repos/<you>/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`) and
   use its `id` field.
3. **Add three repository secrets** on GitHub (this repo → **Settings** → **Secrets and
   variables** → **Actions** → **New repository secret**):
   - `DATABRICKS_HOST` — your workspace URL, **no trailing slash**, e.g.
     `https://adb-xxxxxxxxxxxx.xx.azuredatabricks.net` (not `.../net/`). The workflow now strips a
     trailing slash defensively if one sneaks in, but don't rely on that — paste it clean.
   - `DATABRICKS_TOKEN` — the PAT from step 1, pasted with **no surrounding quotes or spaces**
     (a stray leading/trailing space or a wrapping `"..."` from a copy-paste is a common cause of
     auth failures here)
   - `DATABRICKS_REPO_ID` — the numeric ID from step 2 (from the API's `id` field, not a folder
     path segment)
4. Push to `main` — the workflow (Actions tab → "Sync Databricks Repo") runs automatically and
   the Databricks Repo is updated within seconds, no manual Pull needed.

**Note:** a PAT is a credential — GitHub Actions secrets are encrypted and not readable after
creation, but treat the token itself with the same care as a password (rotate it if it's ever
exposed, and prefer a token scoped to the minimum permissions Databricks allows).

#### Troubleshooting: curl exit code 22 / workflow fails

`curl`'s `-f` flag turns any HTTP 4xx/5xx response into a bare non-zero exit (22) with no visible
error — the updated workflow now prints the actual HTTP status and response body in the Action's
log instead, so check that log first. The three most common causes, in order of likelihood:

1. **Trailing slash on `DATABRICKS_HOST`** — produces a double slash in the request URL
   (`.../net//api/2.0/repos/...`) → 404. The workflow strips this automatically now, but re-check
   the secret's value if this was ever the cause.
2. **Wrong Repo ID** — a `/browse/folders/` ID instead of the API's `id` field (step 2 above) →
   404, "repo does not exist," or similar.
3. **Bad token** — pasted with quotes/whitespace, expired, or lacking permission on that Repo →
   401/403. Regenerate the PAT and re-paste carefully if so.

---

## 8. First run

1. Open `notebooks/01_ingestion_standardisation.py` in the Repo
2. Attach it to the cluster created in step 2 (top-left cluster dropdown)
3. Set the `input_dir` widget at the top of the notebook to the Volume path from step 5/6 (e.g. `/Volumes/treasury_poc/raw/raw`)
4. **Run All**
5. Confirm output: the notebook's final cell shows row counts per entity and should list all three (`LEB`, `KSA`, `QAT`)

---

## Reference: full link list

| Purpose | Link |
|---|---|
| Databricks Community Edition (free signup) | https://community.cloud.databricks.com/ |
| Community Edition docs | https://docs.databricks.com/aws/en/getting-started/community-edition |
| Azure Portal | https://portal.azure.com/ |
| Create Azure Databricks resource | https://portal.azure.com/#create/Microsoft.Databricks |
| Create Storage Account | https://portal.azure.com/#create/Microsoft.StorageAccount |
| Create Access Connector for Databricks | https://portal.azure.com/#create/Microsoft.AccessConnector |
| Databricks account console (Unity Catalog admin) | https://accounts.azuredatabricks.net/ |
| Databricks getting started docs | https://learn.microsoft.com/en-us/azure/databricks/getting-started/ |
| Compute configuration docs | https://learn.microsoft.com/en-us/azure/databricks/compute/configure |
| Unity Catalog get-started docs | https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started |
| Create metastore docs | https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/create-metastore |
| ADLS Gen2 overview | https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction |
| Storage credentials (Access Connector) docs | https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/storage-credentials |
| External locations docs | https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/external-locations |
| Volumes docs | https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/volumes |
| Databricks CLI docs | https://learn.microsoft.com/en-us/azure/databricks/dev-tools/cli/ |
| Databricks Repos / Git integration docs | https://learn.microsoft.com/en-us/azure/databricks/repos/ |
| GitHub personal access tokens | https://github.com/settings/tokens |
| This project's GitHub repo | https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform |
