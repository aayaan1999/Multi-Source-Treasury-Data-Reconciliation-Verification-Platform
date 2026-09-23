# 3-Week POC Plan: All 6 Screens + Camunda 8 Workflow

Decision: **no screens cut** — all 6 screens per `Middle East bank data cleaning and reporting.md`
are in scope for the 3-week demo, alongside Camunda 8 (self-hosted) workflow, fraud/business-rule
detection, and bidirectional Postgres→Databricks sync. To make that fit, two things changed from
earlier drafts of this plan:

1. **Every screen is "shallow-but-complete," not full source-doc depth.** All 6 are visually
   present, wired to real data, and functionally navigable in the demo. None of them implement
   every sub-feature the source doc describes (see section "Per-Screen Shallow Scope" below for
   exactly what's cut per screen and why).
2. **This plan assumes parallel workstreams, not one person working sequentially.** Fitting
   Databricks + Postgres + Camunda + 6 React screens into 15 working days is not credible for a
   single developer doing it in sequence — it requires roughly 3 people (or equivalent capacity)
   working concurrently: one on the data layer, one on Postgres/Camunda/workflow infra, one (or
   two) on the React frontend. If actual team size is smaller than that, **this timeline will
   slip** — that's a real constraint, not a formality.

Three of the previously-blocked KPIs (NIM, Cost-to-Income, ROE) are now computed using documented
placeholder assumptions rather than left blank — see `specs/notebook-03-kpi-summary.md` section 6.
The Camunda Compliance-routing gap is similarly resolved with a documented assumption — see
`specs/camunda-bpmn-process-design.md` section 3. **Every one of these assumptions needs a tooltip
or footnote in the UI wherever it feeds a number**, and needs confirming with whoever owns the
source-of-truth doc before this goes near production — they make the demo complete, they don't
make it verified.

---

## Track A: Data Layer (Databricks + Postgres)

### Week 1
- [ ] Notebook 1: Auto Loader conversion (streaming ingestion, not batch)
- [ ] Notebook 2: no change (already built)
- [ ] Notebook 5 (fraud rules): implement per `specs/notebook-05-fraud-business-rules.md`
- [ ] Notebook 3 (KPI summary): implement per `specs/notebook-03-kpi-summary.md`, all 8 KPIs
  (5 direct + 3 assumption-based)
- [ ] Notebook 4 (exception summary): implement per `specs/notebook-04-exception-summary.md`
- [ ] Notebook 6 (portfolio/branch/scenario snapshot): implement per
  `specs/notebook-06-portfolio-branch-scenario-snapshot.md` — Gold-layer aggregates for Screens
  2, 4, and 5. Independent of Notebook 3 (both only depend on Notebook 2), buildable in parallel
- [ ] **New**: real-time FX rate fetching per `specs/fx-realtime-ingestion.md` — **not a polling
  job or a table**, a shared `get_live_rate()` utility that Notebook 3/6's conversion logic calls
  inline, at run time. Requires picking and confirming currency coverage (USD/EUR/LBP/SAR/QAR) on
  the chosen FX API before implementation, plus deciding failure-handling behavior (spec section 4)
- [ ] **New**: remove/skip Notebook 1-2's `fx_rates` ingestion path — no longer needed once live
  inline fetching replaces it (`specs/fx-realtime-ingestion.md` section 2); revert the
  `DUPLICATE_RATE` note already reverted in `specs/notebook-02-bank-data-quality.md`
- [ ] Run all notebooks against a real cluster; validate against each spec's traceability table

### Week 2
- [ ] PostgreSQL schema (all tables from `PLATFORM-BUILD-PLAN.md` Phase 1, plus `review_outcomes`
  from `specs/bidirectional-sync.md`)
- [ ] Nightly import job: Databricks Gold-layer output → Postgres
- [ ] **New**: stand up one demo Azure Data Factory pipeline per `specs/multi-source-ingestion-adf.md`
  — one simulated database source (watermarked pull) and one simulated API source, both landing
  into ADLS Bronze, triggering Notebook 1 via ADF's Databricks Job activity. **Not** a real
  ERP/CRM integration — demonstrates the pattern, not a production connector

### Week 3
- [ ] Implement bidirectional sync: JDBC read-back of `review_outcomes` before each Notebook 3 run,
  now using the watermark approach (`specs/bidirectional-sync.md`'s "Idempotency" section)
- [ ] Support integration testing / bug-fix the data side of end-to-end runs

---

## Track B: Camunda 8 Infrastructure + Workflow

### Week 1
- [ ] Stand up Camunda 8 self-hosted (Docker Compose: Zeebe + Elasticsearch + Operate + Tasklist)
  — budget a full day even if smooth
- [ ] Model the `transaction-review` BPMN process (3-way gateway: Fraud/Compliance/Operations —
  `specs/camunda-bpmn-process-design.md`), deploy to local Zeebe

### Week 2
- [ ] Build the bridge worker (Postgres → Zeebe process-instance creation)
- [ ] `review_outcomes` write-back service task, wired to Postgres
- [ ] Manual end-to-end test: insert a test exception row, confirm it becomes a Tasklist task in
  the correct group

### Week 3
- [ ] Support React integration against Tasklist's REST API
- [ ] Bug-fix; confirm task creation keeps pace with the nightly import job's volume

---

## Track C: React Frontend (all 6 screens, shallow-but-complete)

### Week 1
- [ ] App skeleton: routing for all 6 screens, Tailwind theming, seeded-user login
- [ ] Screen 4 (Scenario Modelling) — start here: it's the most self-contained screen (no
  Postgres/Camunda dependency once a snapshot endpoint exists), good for parallel early work
  while Track A is still building Notebook 3

### Week 2
- [ ] Screen 1 (Executive Summary) — once `kpi_daily_summary` exists
- [ ] Screen 2 (Portfolio & Credit Risk) — once Track A's extended Notebook 3/6 snapshot exists
- [ ] Screen 5 (Branch & Segment Performance) — same dependency

### Week 3
- [ ] Screen 6 (Report Workflow) — once Track B's Tasklist API is reachable
- [ ] Screen 3 (Regulatory Reporting) — single report template (Capital Adequacy), see shallow
  scope below
- [ ] Integration bug-fixing across all 6 screens

---

## Per-Screen Shallow Scope

What's **in** for the demo vs. deferred to `PLATFORM-BUILD-PLAN.md`'s full-depth version:

**Screen 1 — Executive Summary:** all 8 KPI tiles (3 assumption-based, footnoted). Single
current-day snapshot instead of a 24-month trend line — the trend chart shows one data point and
a note that it accumulates daily going forward. Alert strip: simple threshold-generated sentences.

**Screen 2 — Portfolio & Credit Risk:** loan book by product/segment/branch/currency (current
snapshot), IFRS 9 stage table, top-20 exposures, ageing buckets, LTV distribution — all
computable as one-time aggregates. **Cut:** the 24-month bad-loan trend line by product (needs
historical monthly snapshots this POC's data doesn't have).

**Screen 3 — Regulatory Reporting:** **one** report template (Capital Adequacy, since the source
doc already works out its exact line items), with drill-to-source powered by a
`calculation_audit`-equivalent captured when Notebook 3 computes CAR, 2-3 validation checks
(arithmetic consistency, required-fields), PDF + Excel export for that one template. **Cut:** the
general report-calendar/scheduling engine for arbitrary report types — seed a few example rows
instead of building a scheduler.

**Screen 4 — Scenario Modelling:** all 4 sliders, presets, waterfall chart, 12-month projection,
against an in-memory snapshot fetched once. Full formula chain per the source doc's calculation
order. Least compromised screen — the source doc's own architecture (browser-side recompute) is
inherently light on backend dependencies.

**Screen 5 — Branch & Segment Performance:** branch league table, regional rollup, segment/product
performance, efficiency quadrant scatter — all current-snapshot. **Cut:** "channel usage now vs.
12 months ago" comparison (no historical data); shown as "now" only.

**Screen 6 — Report Workflow:** full scope as speced in `specs/camunda-bpmn-process-design.md` —
this one isn't shallow, since it's the direct replacement for the original brief's exception
workflow and the main new capability this 3-week extension is about.

---

## Explicit Cuts That Remain (things even "shallow-but-complete" doesn't include)

- Real-time sync (bidirectional sync is nightly-batch, now watermark-based rather than full-reload
  — see `specs/bidirectional-sync.md` — but still not event-driven)
- Customer-level fraud baselining / ML anomaly detection — see `specs/notebook-07-fraud-ml-future-phase.md`,
  **explicitly future-phase, not part of this 3-week build** despite the real-time FX and
  multi-source ingestion additions above being in scope. Don't conflate the two — FX/ingestion
  were explicitly added to this plan; the AI/ML fraud layer was explicitly deferred after review
  of its real blockers (no labeled data, no behavioral baseline)
- Multi-report-type Screen 3 (one template only)
- Historical trend lines anywhere they'd require data volume this POC doesn't have
- Auto Loader's full production hardening (schema evolution edge cases beyond basic operation)
- Real ERP/CRM connectors (the ADF pipeline demonstrates the pattern against simulated sources,
  not a production SAP/Salesforce integration — see `specs/multi-source-ingestion-adf.md`)
- `transaction_code_mapping` population (blocked on real source-system code lists that don't
  exist for this POC — see `specs/multi-source-ingestion-adf.md` section 6)

---

## Biggest Schedule Risks (in order)

1. **Team size mismatch.** This plan assumes ~3 concurrent workstreams. If the actual team is
   1-2 people, none of the above changes — the timeline does.
2. **Camunda 8 self-hosted setup + bridge worker** (Track B, Week 1-2) — least-proven integration
   in the whole plan, no existing implementation to lean on.
3. **The assumption-based KPIs and Compliance routing rule need real confirmation**, not just
   documentation — if whoever owns the source-of-truth doc pushes back on the `DEPOSIT_RATE_BY_TYPE`,
   `REGION_CURRENCY`, or table-based Compliance-routing assumptions mid-build, that's rework, not
   just a footnote update.
4. **Notebook 6's assumptions stack on top of Notebook 3's** (`PRODUCT_RATE_TYPE`,
   `ACCOUNT_RATE_TYPE`, `SEGMENT_COST_ALLOCATION`, alongside Notebook 3's `DEPOSIT_RATE_BY_TYPE`/
   `REGION_CURRENCY`/tier1-as-equity) — five distinct placeholder assumptions across two
   notebooks feed Screens 1, 2, 4, and 5. Confirming all five with whoever owns the source-of-truth
   doc is real, non-trivial follow-up work, not a footnote task.
5. **Multi-source ingestion no longer needs ADF** — revised to 5 free cloud sources (Neon,
   Mockaroo, IMF API, Salesforce Developer Edition, Google Sheets) pulled directly by small
   Databricks ingestion notebooks, per the MVP revision of `specs/multi-source-ingestion-adf.md`.
   Lower risk than the original ADF-based design, but still 5 separate accounts/credentials to
   set up and 5 separate small ingestion notebooks to write — not zero-effort just because no new
   Azure resource is needed.
6. **FX API currency coverage is unverified, and live-call failure handling needs a real
   decision** — `specs/fx-realtime-ingestion.md` explicitly flags that LBP/QAR coverage needs
   confirming on whichever provider is picked before relying on
   it; a provider that silently omits one of our five currencies would only surface as missing
   data partway through implementation, not up front.
