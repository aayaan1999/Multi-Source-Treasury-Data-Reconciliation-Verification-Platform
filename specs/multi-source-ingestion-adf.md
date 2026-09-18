# Spec: Multi-Source Ingestion (MVP/Demo — Free Cloud Sources)

**Status:** Spec only — not yet implemented
**New for:** the "multiple data sources" requirement added to `3-WEEK-POC-PLAN.md`
**Revised for:** demo/MVP scope — real free cloud sources instead of simulated/hypothetical ones,
and ADF's role downgraded from required to optional (see section 3)
**Depends on:** feeds into `specs/notebook-01-bank-data-ingestion.md`'s Auto Loader input, does
not change Notebook 1's own logic
**Research grounding:** see sources at the end of this file

---

## 1. Objective

Demonstrate ingesting from multiple *real* external systems — not manually-uploaded CSVs, and not
hypothetical/simulated ones — using genuinely free cloud services, **without making Databricks/
Notebook 1 source-aware.** Notebook 1 still only knows "read files from a directory."

## 2. Why This Revision: Everything Is Now Cloud, Not On-Prem

The earlier version of this spec (and the on-prem CBS/LOS/Treasury-system discussion in this
session) assumed real enterprise source systems, most plausibly on-premises at a bank — which is
why Self-Hosted Integration Runtime (SHIR) mattered so much. **For a demo/MVP, every source below
is already cloud-hosted and reachable over the public internet.** This removes the single biggest
piece of complexity from the earlier design — no SHIR, no VPN/ExpressRoute, no on-prem network
access at all.

## 3. Architecture Simplification: ADF Becomes Optional, Not Required

ADF's core value — SHIR for on-prem reach, and a 90+ connector catalog for well-known enterprise
systems — matters much less when every source is already a plain REST API or a cloud Postgres
database reachable via JDBC. **Recommendation for this MVP: skip standing up ADF entirely.**
Instead, add a small **ingestion notebook** (or a couple of them) in Databricks itself that calls
these free APIs / reads these free databases directly and lands the result into ADLS Bronze —
simpler, one less Azure resource to provision, and no loss of the "Notebook 1 stays source-agnostic"
property, since Notebook 1 still only reads from Bronze regardless of how it got there.

**ADF remains documented** (section 7) as the enterprise-scale answer, for narrative purposes if a
client audience asks "how would this scale to real ERP/CRM systems" — but it's not something to
actually stand up for this demo.

## 4. The 5 Free Cloud Sources

| # | Stands in for | Service | Why this one |
|---|---|---|---|
| 1 | Core Banking System (customer/account data) | **Neon** (free serverless Postgres) | Free tier: 100 CU-hours, 0.5 GB storage. Chosen over Supabase specifically because **Supabase pauses projects after 7 days of inactivity, requiring manual restoration** — a real risk for an infrequently-run demo pipeline. Neon auto-wakes in ~570ms after idling, which tolerates a gap between demo runs without breaking |
| 2 | Loan Origination System | **Mockaroo** (free mock API/data generator) | Free tier: up to 1,000 API requests/day, up to 1,000 rows per download, JSON/CSV/SQL/Excel output. Lets you define a realistic loan-origination schema and get a live mock REST endpoint — demonstrates the "pull from an external REST API" pattern without needing a real LOS vendor account, which doesn't exist for this POC anyway |
| 3 | Regulatory/macro data feed | **IMF Data API** (SDMX 2.1/3.0, free, no key required) | A genuinely official, freely-licensed institutional data source — better narrative fit for "regulatory feed" than a mocked one, since it's real published IMF data, not synthetic |
| 4 | CRM | **Salesforce Developer Edition** (free, doesn't expire with active use) | A real CRM system's REST/Bulk API, not a mock — comes pre-seeded with sample Account/Contact data. 5 MB storage cap on the free tier is fine for demo volume. This is the strongest "real enterprise SaaS" ingestion demo of the five, since it's the actual product a bank's CRM team would use |
| 5 | Branch/Finance ERP (opex, staffing) | **Google Sheets + Sheets API** (free) | Deliberately realistic, not a hack — branch-level cost data at many banks genuinely still lives in a spreadsheet maintained by finance, not a full ERP module. Demonstrates the simplest possible "external source" ingestion pattern, useful as the easiest one to build first |

**Bonus — solves a different problem**: **PaySim** (Kaggle's synthetic mobile-money fraud
dataset, free download, ~6.3M transactions, hourly-granularity timestamps, 8,213 real labeled
fraud cases) directly addresses three of the blockers documented in
`specs/notebook-07-fraud-ml-future-phase.md` section 1 (no labeled data, no realistic volume, no
sub-day timestamp granularity — PaySim's `step` field is hourly, unlike our schema's date-only
`transactions.date`). **This doesn't slot in as a 6th ingestion source for the current pipeline**
— PaySim's schema (`step`, `type`, `amount`, `nameOrig`, `oldbalanceOrg`, `newbalanceOrig`,
`nameDest`, `oldbalanceDest`, `newbalanceDest`, `isFraud`) doesn't match `transactions`
(no `account_id`/`customer_id`/`channel`/`currency` as such) and is from a different market
(African mobile-money, not MENA banking) — it would need a real mapping/ETL exercise, not a
drop-in load. Worth revisiting specifically when Notebook 7 moves out of future-phase status, not
now.

## 5. Per-Source Ingestion Mechanism

| Source | Connector | Ingestion notebook logic |
|---|---|---|
| Neon (Postgres) | Spark JDBC read | `spark.read.jdbc(url=neon_url, table="customers", properties=...)`, watermarked on `updated_at` per `specs/bidirectional-sync.md`'s established pattern, write result to Bronze as Parquet |
| Mockaroo | REST GET | Python `requests` call against the mock endpoint (API key in a Databricks secret scope), write JSON response to Bronze |
| IMF API | REST GET (SDMX) | Same pattern as Mockaroo — no key needed for IMF's public API |
| Salesforce | REST/Bulk API | OAuth2 credentials in a Databricks secret scope; `simple-salesforce` (Python) or direct REST calls against Salesforce's API, write result to Bronze |
| Google Sheets | Sheets API | Service-account credentials (JSON key) in a Databricks secret scope, `gspread` (Python) or direct API call, write result to Bronze |

All five converge on the same output shape: a file in ADLS Bronze. **Notebook 1 needs zero
awareness of which of these five produced any given file** — same source-agnostic guarantee as
the original design, just via direct Databricks-side pulls instead of ADF.

## 6. Credentials

Every API key/OAuth token/service-account JSON above goes into a **Databricks secret scope** — same
pattern already established for the ADLS credential and the FX API key in
`specs/fx-realtime-ingestion.md`. None of these five credentials should ever appear in notebook
code.

## 7. If This Ever Needs to Scale to Real Enterprise Sources (ADF, Documented Not Built)

The original ADF-based design remains valid for a future, real-client engagement where sources are
genuinely on-prem legacy systems (real CBS, real LOS, real treasury middle-office system) — see
this session's earlier discussion for the on-prem connection pattern (Self-Hosted Integration
Runtime, VPN/ExpressRoute, ADF's native connector catalog, the Databricks Job activity trigger).
**Don't build this now** — it's the right answer for a different scope than this MVP.

## 8. Centralized Transaction Coding — Still a Real Schema Gap

Unchanged from the prior version of this spec: mapping each source's transaction codes to one
centralized code needs a `source_system` column and a `transaction_code_mapping` reference table
that don't exist in the current schema, and can't be populated without real source-system code
lists. For these 5 demo sources specifically, this is more tractable than it was for hypothetical
enterprise systems — Mockaroo's mock schema and Google Sheets' columns can simply be *designed*
with a `source_code` field from the start, since you control their schema. Salesforce and Neon
would need actual field mapping once their schemas are defined.

## 9. Implementation Approach

One Databricks notebook per source, all converging on the same Bronze landing convention: one
subfolder per source (e.g. `bronze/neon_customers/`, `bronze/mockaroo_loans/`), written with
`.format("delta")`, timestamped so reruns don't silently overwrite. Notebook 1 reads from Bronze
unchanged — per section 5, it stays source-agnostic.

**Shared setup (once, before any source-specific work)**
- Create a Databricks secret scope (e.g. `multi-source-demo`) and add each credential to it as its
  account is provisioned: Neon connection string, Mockaroo API key, Salesforce OAuth client
  ID/secret, Google service-account JSON.
- A small Delta control table tracking the last watermark pulled per source (needed for Neon's
  incremental read, section 10 below).

**1. Neon (Postgres)**
- Provision a free Neon project; create `customers`/`accounts` tables with sample rows.
- `spark.read.jdbc(url=neon_jdbc_url, table="customers", properties={"user": ..., "password": ...})`.
- Watermark: filter `WHERE updated_at > last_watermark` (read from the control table), update the
  control table with the new max `updated_at` after a successful write — this is what makes reruns
  incremental instead of full-table each time, per the pattern in `specs/bidirectional-sync.md`.
- Write to `bronze/neon_customers/`.

**2. Mockaroo**
- Design a loan-origination schema in Mockaroo's UI (`loan_id`, `customer_id`, `amount`, `product`,
  `origination_date`, ...); get the mock REST endpoint + API key.
- `requests.get(mockaroo_url, headers={"X-API-Key": dbutils.secrets.get("multi-source-demo", "mockaroo_key")})`,
  parse the JSON response into a Spark DataFrame.
- Write to `bronze/mockaroo_loans/`.

**3. IMF Data API**
- No account or key needed — call the public SDMX endpoint directly.
- Same `requests.get()` pattern, no auth header; parse the SDMX/JSON response into a DataFrame.
- Write to `bronze/imf_macro/`.

**4. Salesforce Developer Edition**
- Sign up for a free Developer org (comes pre-seeded with sample Account/Contact records).
- Register a Connected App to get an OAuth client ID/secret; do the OAuth token exchange (or use
  `simple-salesforce`'s login helper), credentials pulled from the secret scope.
- Pull via REST (`/services/data/vXX/query?q=SELECT+Id,Name+FROM+Account`) or the Bulk API for
  larger volume.
- Write to `bronze/salesforce_accounts/`.

**5. Google Sheets**
- Create a Google Cloud service account; manually share the target Sheet with that service
  account's email (one-time action outside any notebook).
- Authenticate `gspread` with the service-account JSON key from the secret scope;
  `sheet.get_all_records()` → DataFrame.
- Write to `bronze/branch_finance/`.

**Scheduling**
- A Databricks Job with 5 parallel ingestion tasks (one per source above), followed by Notebook 1
  as the downstream task — matching the existing nightly-run pattern. Notebook 1 requires no code
  changes to consume any of the five; if it does, the source-agnostic design (section 5) has
  failed.

**Relative effort, easiest to hardest:** IMF (no auth, plain GET) and Mockaroo (API-key GET) are
the simplest. Neon reuses an existing watermark pattern. Google Sheets needs one manual
service-account share step. Salesforce is the most involved, due to the OAuth flow.

## 10. Acceptance Criteria

- [x] IMF API: ingestion notebook written (`notebooks/multi_source_imf_ingestion.py`) — calls the
      public CompactData SDMX endpoint per country, writes to `bronze_imf_macro`. **Not yet run
      against a live cluster** — the per-country fetch, JSON shape, and empty-result handling are
      unverified against IMF's actual current response format.
- [x]/[ ] Neon: **written** (`notebooks/multi_source_neon_ingestion.py`), watermarked via a
      `multi_source_watermarks` control table. **Cannot run yet** — blocked on provisioning a
      Neon project and populating the `neon_jdbc_url`/`neon_user`/`neon_password` secrets.
- [x]/[ ] Mockaroo: **written** (`notebooks/multi_source_mockaroo_ingestion.py`). **Cannot run
      yet** — blocked on designing the mock schema in Mockaroo's UI and generating
      `mockaroo_api_key`.
- [x]/[ ] Salesforce: **written** (`notebooks/multi_source_salesforce_ingestion.py`), username-
      password OAuth flow. **Cannot run yet** — blocked on a Developer org signup, registering a
      Connected App, and populating `sf_client_id`/`sf_client_secret`/`sf_username`/`sf_password`/
      `sf_security_token`.
- [x]/[ ] Google Sheets: **written** (`notebooks/multi_source_google_sheets_ingestion.py`), via
      `gspread` + a service-account key. **Cannot run yet** — blocked on creating the service
      account, manually sharing the target Sheet with it, and populating
      `google_service_account_json`.
- [ ] Notebook 1 requires **zero code changes** to pick up files landed by any of these five
      sources — if it needs changes, the source-agnostic design has failed. Not yet verified even
      for IMF, since IMF's own notebook hasn't run on a cluster yet.

## 11. Non-Goals

- No ADF deployment for this MVP (documented as the future path, section 7)
- No real ERP/CRM belonging to an actual bank (Salesforce Developer Edition is a real CRM
  *product*, but seeded with Salesforce's own sample data, not a real bank's data)
- No full CDC (watermark-based JDBC pull only, same reasoning as the prior version of this spec)
- PaySim integration (section 4's "bonus" note) — revisit when Notebook 7 moves out of
  future-phase, not part of this ingestion work

---

**Research sources** (grounding this spec, fetched during this session):
- [Neon vs Supabase Free Tiers: We Benchmarked Both So You Don't Have To | daily.dev](https://daily.dev/posts/5rxzeuptx)
- [Introducing the New Salesforce Developer Edition | Salesforce Developers Blog](https://developer.salesforce.com/blogs/2025/03/introducing-the-new-salesforce-developer-edition-now-with-agentforce-and-data-cloud)
- [Mockaroo - Random Data Generator and API Mocking Tool](https://www.mockaroo.com/mock_apis)
- [API Page - IMF Data - International Monetary Fund](https://data.imf.org/en/Resource-Pages/IMF-API)
- [Synthetic Financial Datasets For Fraud Detection | Kaggle (PaySim)](https://www.kaggle.com/datasets/ealaxi/paysim1)
- [Announcing the new Databricks Job activity in ADF! | Microsoft Community Hub](https://techcommunity.microsoft.com/blog/azuredatafactoryblog/announcing-the-new-databricks-job-activity-in-adf/4410939)
