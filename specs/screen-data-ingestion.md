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

`/ingestion`, first tab in the menu. "Data ingestion" pill, heading "Bring data in", then:

- **Top right:** "Schedule: on file arrival" (the pipeline's real trigger, `databricks.yml`) and **Run
  all sources now** (CFO/admin only). It starts the Databricks job through Refresh now
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
| Schedule button | `databricks.yml` file-arrival trigger | Real (hard-coded label matching the file) |
| Run all sources now | Refresh now, Databricks Jobs API | Real (needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN`) |
| Sources connected, Connect a source | Catalogue in `app/connectors.py` (core banking files, Salesforce, PostgreSQL, REST API, AWS S3, Snowflake) + `source_connectors` (migration 018): non-secret settings only | **Real state** (ING-1 part 1); "Test connection" checks the form, not a live sign-in |
| Scheduled pulls | `DEMO["schedules"]` | Demo (ING-2) |
| Upload files (CSV, JSON, Parquet, XLSX, XML, PDF) | Browser only: type and 2 GB size checked, progress and a completion toast shown, **nothing sent** | Demo (ING-3) |
| Run all sources now, each source's Sync | `POST /ingestion/run`, `POST /ingestion/sources/{key}/sync` → Databricks `POST /api/2.1/jobs/run-now` (via refresh.py); spinner and toasts | Real (needs `DATABRICKS_HOST` / `DATABRICKS_TOKEN`) |

The live data today has one source system, `CORE_CSV`: CSV files per data type from the landing volume,
tagged by country (Lebanon, Saudi Arabia, Qatar, plus "Group" for bank-wide tables). It shows as
"Lebanon Core Banking · File (CSV) · transactions.csv" and so on.

## 3a. Connecting a source (added 2026-09-29, client demo)

- **Connect** opens a form drawn from the source's field list; **Connect & Save** stays disabled until
  every required field is filled and well-formed (https:// addresses, ports 1-65535). The server checks
  the same rules again (`connectors.validate`) and refuses unknown fields.
- **Test connection** (`POST /ingestion/sources/{key}/test`) checks the details are complete and
  well-formed and says so; it does not sign in to the system yet (backlog ING-1).
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

## 4. Acceptance criteria

- [x] Screen matches the deck's slide 3 layout and lists all four points - built, not yet checked in a browser
- [x] Stat cards and Recent ingestions use the real latest run when there is one - `tests/test_ingestion.py`; checked against live Neon on 2026-09-29 (2,635 received, 2,630 kept, 5 held back, 8 files, 18 loads)
- [x] Every demo block is labelled "Demo data" - `Ingestion.test.jsx`
- [x] Uploaded files are checked but never sent - `Ingestion.test.jsx`
- [x] Run all sources now: CFO/admin only; a missing Databricks connection is explained, not an error page - `Ingestion.test.jsx`
- [x] Connect form validation, Test, Connect & Save, Configure, Disconnect, Sync, Run all with spinner and toasts - `Ingestion.test.jsx`, `tests/test_source_connectors.py`; connect / disconnect run against live Neon on 2026-09-29, no secret stored
- [ ] Checked in a browser, light and dark theme
