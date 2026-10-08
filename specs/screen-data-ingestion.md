# Spec: Data Ingestion screen

**Status:** Built 2026-09-29 (backend + frontend, with tests); not yet checked in a browser. Part real,
part demo content - see section 3.
**Reference:** client demo deck, `project-docs/client-demo/AppBay-Client-Demo.pdf`, slide 3 ("Step 1 -
Data Ingestion: every source, one way in"); requested in the manager review of 2026-09-29.
**Backlog:** `project-docs/CLIENT-FEEDBACK-BACKLOG.md` section 9 (ING-1..6) turns the demo parts into
real data.

---

## 1. Objective

Show where the bank's data comes from and whether each load worked, before anyone looks at a number
built from it. The deck lists four points, all on this screen:

1. Multi-source ingestion: core banking, ERP, CRM, databases and spreadsheets.
2. Upload files (CSV, XLSX, JSON, XML, PDF) or connect a live source.
3. Scheduled and automatic pulls, so no one has to remember.
4. Status tracked for every load: records received, success or failure.

## 2. Layout (as in the deck)

`/ingestion`, first tab in the menu, and where sign-in lands for everyone who uses it (`landingOf`). "Data ingestion" pill, heading "Bring data in", then:

- **Top right:** **Run All Sources** (CFO/admin only). (The "Schedule: on file arrival" label was removed
  on 2026-09-30 at the client's request.) It starts the Databricks job through Refresh now
  (`POST /refresh`, `specs/refresh-now.md`) and says plainly when the app isn't connected to Databricks
  (503).
- **Four stat cards** with a yellow top edge (red when there are failed loads): Sources connected,
  Files in latest run, Records ingested (kept · held back with a reason), Failed loads (with the first
  failure).
- **Left:** Upload files (drag and drop or Browse files; the accepted formats; one row per file with a
  progress bar) and Scheduled pulls (source, cadence, next pull).
- **Right:** Connect a source (six connector cards: Connected, or a Connect button) and Recent
  ingestions (source, type, data, records received, status with the held-back count or failure reason,
  last run).

## 3. Real and demo content

`GET /api/v1/ingestion/overview` (`backend/app/routers/ingestion.py`) returns the whole screen in one
call. Each block carries `demo: true|false`, and every demo block shows a **Demo data** label that
explains itself on hover or focus, the same pattern as the existing "Assumption" labels.

| Block | Source | Real? |
|---|---|---|
| Files, records received / kept / held back, failed loads | Latest run in `pipeline_reconciliation` (Notebooks 1-2 via `load_to_postgres.py`) | **Real** when a run exists; demo rows otherwise |
| Recent ingestions | Same rows, one per source × country × data type; "failed" = the completeness check's "No rows delivered" (FLOW-1b) | **Real** when a run exists; demo rows otherwise |
| Run All Sources | Refresh now, Databricks Jobs API | Real (needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN`) |
| Sources connected, Connect a source | Catalogue in `app/connectors.py` (core banking files, Salesforce, PostgreSQL, REST API, AWS S3, Snowflake) + `source_connectors` (migration 018): non-secret settings only | **Real state** (ING-1 part 1); "Test connection" connects for real for PostgreSQL and the REST API (sections 3c, 3d), checks the form only for the others |
| Scheduled pulls | `DEMO["schedules"]` | Demo (ING-2) |
| Upload files (the pipeline's eight CSVs) | `POST /ingestion/upload` → Databricks Files API into the landing volume (section 3b) | **Real** (ING-3; needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN`) |
| Run All Sources, each source's Sync | `POST /ingestion/run`, `POST /ingestion/sources/{key}/sync` → Databricks `POST /api/2.1/jobs/run-now` (via refresh.py); spinner and toasts | Real (needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN`) |

The live data today has one source system, `CORE_CSV`: CSV files per data type from the landing volume,
tagged by country (Lebanon, Saudi Arabia, Qatar, plus "Group" for bank-wide tables). It shows as
"Lebanon Core Banking · File (CSV) · transactions.csv" and so on.

## 3a. Connecting a source (added 2026-09-29, client demo)

- **Connect** opens a form drawn from the source's field list; **Connect & Save** stays disabled until
  every required field is filled and well-formed (https:// addresses, ports 1-65535). The server checks
  the same rules again (`connectors.validate`) and refuses unknown fields.
- **Test connection** (`POST /ingestion/sources/{key}/test`) checks the details are complete and
  well-formed and says so. For PostgreSQL it also signs in for real (section 3c); for the others it
  does not sign in yet (backlog ING-1), and the answer says which it was (`live`). A failed live
  sign-in answers 200 with `ok: false`; the form shows the reason and an error toast.
- **Connect & Save** (`POST /ingestion/sources/{key}/connect`) calls
  `connect_to_databricks_pipeline()`: passwords, keys and tokens go to the Databricks secret scope
  `bank-data-sources` as `<source>-<field>`, where ingestion notebooks read them. They are **never**
  written to Postgres, the audit log or the response. Not connected to Databricks → nothing is stored,
  the card says "Saved without credentials" and the toast explains. The non-secret settings go to
  `source_connectors`; one `SOURCE_CONNECTED` audit row, without secrets.
- A connected card shows **Configure** (the saved settings, secrets empty, plus **Disconnect**) and
  **Sync**. Every change updates the page in place. CFO/admin only, like Refresh now.
- Non-secret settings (instance URL, client ID...) are also put in the scope, so a source's notebook needs
  nothing else; fields an older form asked for are deleted from the scope. **Disconnect** deletes all of
  the source's keys from the scope.

## 3b. Salesforce, end to end (2026-09-29)

- **Salesforce side:** an **External Client App** with **Enable Client Credentials Flow** and a **Run As
  (Username)** in its Policies. New orgs can't create Connected Apps since Spring '26, and External
  Client Apps don't support the username-password flow, so the form asks only for the **Instance URL
  (My Domain)**, **Consumer key** and **Consumer secret**. The token request must go to the My Domain
  address; `login.salesforce.com` is refused for this flow.
- **Pipeline:** `notebooks/multi_source_salesforce_ingestion.py` is the `salesforce_ingest` task of
  `bank-data-pipeline` (no dependencies; runs alongside the core banking load). It reads
  `bank-data-sources/salesforce-{instance_url,client_id,client_secret}`, signs in with client
  credentials, reads every page of `SELECT Id, Name, Industry, BillingCountry, CreatedDate FROM Account`
  into `bronze_salesforce_accounts` (tagged `source_system = SALESFORCE`) and writes one row to Neon
  `ingestion_runs` (migration 019), which "Recent ingestions" lists. Not connected → exits "skipped";
  sign-in or query failure → records "failed" with Salesforce's error code and exits without failing
  the pipeline run.
- **Not yet:** Salesforce Accounts are not merged into `customers` or compared with them
  (`specs/multi-source-reconciliation.md` covers the Neon slice only).
- `databricks.yml` has a `trigger_pause_status` variable (default UNPAUSED). The 2026-09-29 deploy used
  `--var trigger_pause_status=PAUSED` to keep file-arrival runs off, as they were in the workspace.

## 3c. PostgreSQL = the core banking system, end to end (2026-10-08)

Not yet run live on Databricks or checked in a browser; backend and frontend tests pass.

- **What it is for:** the core banking database the reconciliation compares our data with
  (`specs/multi-source-reconciliation.md`, source `neon`). It must hold `customers` (customer_id, name,
  segment, risk_rating, branch_id) and `accounts` (account_id, customer_id, type, currency, balance),
  with the same IDs as ours; other columns are ignored (`connectors.CORE_BANKING_TABLES`). It must be
  reachable from Databricks serverless compute over the internet.
- **Form:** Host, Port, Database, Username, Password (use a read-only user). **Test connection** signs in
  from the API server with SSL required, in a read-only session with a 10-second limit, checks both
  tables and their columns, and answers "Signed in to host/db: found N customers and M accounts", or the
  database's own reason (wrong password, no such table, missing column). The password is never in the
  answer. Pointing the form at the app's own database (same host - Neon's pooled host counts - and
  database as `DATABASE_URL`) is refused by both Test connection and Connect & Save (422).
- **Pipeline:** `core_banking_ingest` (`notebooks/multi_source_neon_ingestion.py`) reads
  `bank-data-sources/postgresql-*`, reads both tables with Databricks' `postgresql` format (serverless
  rejects generic JDBC), and **replaces** `bronze_neon_customers` / `bronze_neon_accounts` - a full
  snapshot each run, replacing the earlier `updated_at` watermark (needed a column the bank may not have,
  missed deletions, and kept an old database's watermark). One `ingestion_runs` row per table, shown as
  "PostgreSQL · Database" under Recent ingestions. Not connected → "skipped"; a failed read → "failed"
  with the first line of the error, without failing the run. `core_banking_reconciliation`
  (`multi_source_reconciliation.py`, `source=neon`) runs after it and `quality`, and skips unless this run
  loaded core banking; `load_postgres` waits for it.
- **Replaces** the hand-made `multi-source-demo` secret scope (`neon_jdbc_url`, ...), which nothing reads
  any more.

## 3d. REST API = the loan origination system, end to end (2026-10-08)

Not yet run live on Databricks or checked in a browser; backend and frontend tests pass.

- **What it is for:** a third system our data is compared with: the loan origination system's loans
  against ours (`multi_source_reconciliation.py`, source `los`, shown as "Loan origination system" on the
  Reconciliation screen). Compared per `loan_id`: customer_id, product, currency (exact), principal and
  outstanding (more than $1), interest rate (more than 0.001 percentage points). Corrections ("our copy is
  wrong") go to `loans` like accounts and customers.
- **Demo system:** a free **Supabase** project whose `loans` table Supabase serves as a REST API.
  `scripts/seed_loans_api.py` (Postgres connection string in the git-ignored `db/loans_api_demo.env`,
  Session pooler) copies the app's loans into it and plants one difference per feature: +15 on three
  loans (one group), +25,000 on one (important), a rate change, a product change, a currency change
  (important), a product in capitals (cleared automatically), one loan left out and one extra loan. The
  table is read-only to the publishable key (row-level security, one SELECT policy). Supabase pauses free
  projects after about a week without activity.
- **Form:** Base URL `https://<project>.supabase.co/rest/v1`, Endpoint `/loans`, Auth header `apikey`,
  API key = the project's publishable key. **Test connection** calls the API for one loan, asking for the
  total (`Prefer: count=exact`), and answers "Reached …: found N loans with every field the comparison
  needs", or why not (the API's status and message, no loans, missing fields, not JSON, unreachable). The
  key is never in the answer.
- **Pipeline:** `loans_api_ingest` (`notebooks/multi_source_rest_api_ingestion.py`) reads
  `bank-data-sources/rest_api-*`, reads every page (`limit`/`offset`, 1,000 at a time, stopping when the
  API ignores paging), and **replaces** `bronze_los_loans`. No loans at all, or a missing field, fails the
  task rather than turning every loan into a "missing" task. One `ingestion_runs` row, shown as
  "REST API · API · loans". `loans_api_reconciliation` (`source=los`) runs after it and `quality`, skips
  unless this run loaded the loan system; `load_postgres` waits for it.

## 3b. Upload files (added 2026-09-30, ING-3)

The upload box sends the day's core banking files straight into the pipeline's landing volume
(`/Volumes/dbw_bankx_treasury_poc/raw/raw/resources`, `databricks.yml`'s `landing_path`; override with
`DATABRICKS_LANDING_PATH` in `backend/.env`), where Notebook 1 reads them.

- **What is accepted:** only the eight CSVs Notebook 1 reads: `customers`, `accounts`, `loans`,
  `transactions`, `branches`, `capital_positions`, `liquidity_daily`, `fx_rates`. A name may carry a
  suffix after `_`, `-`, `.` or a space (`Transactions_2026-09-30.csv` is stored as `transactions.csv`,
  replacing the file there). Other formats need a reader in Notebook 1 first (PDF needs table
  extraction, `PREREQUISITES.md` question 8), so they are refused.
- **Checks in the browser** (`Ingestion.jsx`, `pipelineFile`): has a type, is CSV, is one of the eight
  names, not empty, at most 100 MB, not added twice. A refused file is never sent.
- **Checks on the server** (`backend/app/routers/ingestion.py`, `POST /api/v1/ingestion/upload`, raw
  body + `X-File-Name`): the same name rule, not empty, at most 100 MB, UTF-8, and the header row has
  every column Notebook 1 needs for that table (`UPLOAD_FILES`). 400 with the reason otherwise.
- **A file that would replace the data (added 2026-09-30):** for `customers`, `accounts`, `loans` and
  `branches`, the server compares the file's record ids with those the platform has now. A file that
  would remove more than 20% of them (`REPLACE_WARN_SHARE`) is another snapshot or a partial file, so it
  comes back 409 with the numbers ("would remove 186 of the 214 customers … and add 372 new ones"). The
  file waits in the box with **Send anyway** (resent with `X-Replace-Confirmed: yes`, recorded in the
  audit row) and **Don't send**. Daily series (transactions, liquidity, FX, capital) are not checked.
  Why: on 2026-09-30 the 30 Sep test set, built from other synthetic data, replaced the demo's customers
  and raised about 500 tasks (180 CRM breaks, 288 possible duplicates, 34 fraud cases).
- **Writing:** Databricks Files API `PUT /api/2.0/fs/files{path}?overwrite=true` with the app's token
  (the token needs WRITE VOLUME on the volume). Databricks errors come back as 502 with Databricks'
  message; no Databricks settings → 503.
- **Who:** the CFO and the Platform Administrator (same rule as Run All Sources); everyone else sees
  "Only the CFO or the Platform Administrator can upload files." and a drop does nothing. The auditor is
  refused by the read-only guard. One `FILE_UPLOADED` audit row per file (name, rows, bytes, path).
- **Starting the pipeline:** the file-arrival trigger starts the job about 2 minutes after the last file
  (`wait_after_last_change_seconds: 120`). The reply reads the job's trigger: when it is **paused** (as
  after the 2026-09-29 deploy with `trigger_pause_status=PAUSED`) the file still lands and the message
  says to press **Run All Sources** once all files are in.
- **Not done:** virus scanning, multi-file "batch" upload as one unit, files other than the eight CSVs.

## 4. Acceptance criteria

- [x] Screen matches the deck's slide 3 layout and lists all four points - built, not yet checked in a browser
- [x] Stat cards and Recent ingestions use the real latest run when there is one - `tests/test_ingestion.py`; checked against live Neon on 2026-09-29 (2,635 received, 2,630 kept, 5 held back, 8 files, 18 loads)
- [x] Every demo block is labelled "Demo data" - `Ingestion.test.jsx`
- [x] Upload files: the eight CSVs are checked in the browser and on the server, written to the landing folder, audited; CFO/admin only; a paused trigger is explained - `Ingestion.test.jsx`, `tests/test_file_upload.py` (Files API faked); live landing folder and trigger state read on 2026-09-30, no file written by the tests
- [x] Run All Sources: CFO/admin only; a missing Databricks connection is explained, not an error page - `Ingestion.test.jsx`
- [x] Connect form validation, Test, Connect & Save, Configure, Disconnect, Sync, Run all with spinner and toasts - `Ingestion.test.jsx`, `tests/test_source_connectors.py`; connect / disconnect run against live Neon on 2026-09-29, no secret stored
- [ ] Checked in a browser, light and dark theme
