# Platform Build Plan

Phased roadmap for the full platform described in `Middle East bank data cleaning and reporting.md`.
Supersedes `7-DAY-PLAN.md` for everything past the Databricks layer — six screens on a real
banking data model is a multi-week build, not a 1-week POC. `7-DAY-PLAN.md` still stands for its
original Days 1-3 (Databricks sample data + notebooks).

Each phase below assumes ~1 week, adjust to actual team velocity. Phases are ordered so each one
produces something demoable, rather than front-loading all plumbing before anything is visible.

---

## Phase 0 — Databricks Data Layer (in progress)

Owner: Databricks Developer + Claude Code. Unchanged from `bank-x poc-brief.md` section 5.

- [x] Sample entity CSVs (Lebanon, KSA, Qatar) with injected data-quality issues
- [x] Notebook 1 — Ingestion & Standardisation → `treasury_positions_raw`
- [x] Notebook 2 — Data Quality Verification → `treasury_positions_clean`, `treasury_positions_exceptions`
- [ ] Notebook 3 — Reconciliation & Consolidated Report → `treasury_consolidated_report`
- [ ] Notebook 4 — Exception Summary Report → `exception_summary`
- [ ] Run all four against a real Databricks cluster (Community Edition or Azure) and validate output

**Exit criteria:** four Delta tables produced and CSV-exportable; this is the first real data feed
into the application layer built from Phase 1 onward.

---

## Phase 1 — Foundation

Owner: Claude Code (backend/frontend scaffolding) + Dev Lead (environment decisions).

- [ ] PostgreSQL schema: all entity tables (`customers`, `accounts`, `loans`, `branches`),
  time-series tables (`transactions`, `capital_positions`, `liquidity_daily`, `fx_rates`), and
  workflow/reporting tables (`report_definitions`, `report_instances`, `report_line_items`,
  `validation_rules`, `calculation_audit`, `risk_weights`, `submitted_files`, `users`, `roles`,
  `workflow_steps`, `workflow_instances`, `tasks`, `comments`, `audit_log`, `limits`, `breaches`)
- [ ] FastAPI project skeleton with DB models + migrations (SQLAlchemy + Alembic)
- [ ] Synthetic data generator for customers/accounts/loans/transactions/branches/capital/liquidity/FX
  — no real source exists for these yet; check scale/realism expectations with the user before
  generating large volumes
- [ ] Nightly import job: Databricks CSV exports (`treasury_consolidated_report`, `exception_summary`,
  `treasury_positions_exceptions`) → PostgreSQL tables
- [ ] React app skeleton: routing for all 6 screens (placeholder pages), Tailwind theming, seeded-user
  login (analyst/reviewer/approver/admin)
- [ ] `limits` table + a nightly breach-check job that creates `tasks`/`breaches` rows automatically

**Exit criteria:** empty-but-navigable app, seeded synthetic data in Postgres, Databricks output
flowing into Postgres nightly.

---

## Phase 2 — Screens 1 & 6 (the treasury-reconciliation demo case)

These two screens most directly cover the original POC brief's requirements (exception review,
approval, consolidated view, audit trail), so they come first — this is the fastest path to a
demoable story using data that's actually real (Databricks treasury output), not synthetic.

- [ ] **Screen 6 — Report Workflow**: My Tasks landing view, visual approval chain (prepared →
  reviewed → approved → submitted), review screen with comments + approve/return-with-comment,
  breach alerts from Phase 1's `limits`/`breaches` tables, insert-only `audit_log` (enforce via DB
  grants: INSERT only, no UPDATE/DELETE)
  - Wire the treasury `treasury_positions_exceptions` records in as the concrete task type here —
    this is the direct replacement for the brief's Appian Exception Queue + Case Detail views
- [ ] **Screen 1 — Executive Summary**: 8 KPI tiles, 24-month trend chart, plain-language alert
  strip, nightly precomputed summary table (do not compute live)
  - CAR/LCR/NIM/ROE/cost-to-income/dollarization need `capital_positions`/`liquidity_daily`/
    `accounts`/`loans` data (synthetic, from Phase 1) — only the treasury exposure angle has real
    Databricks data behind it initially

**Exit criteria:** an officer can see an exception, claim/review it, approve or reject with a
mandatory comment, and see it reflected in an audit trail — the original brief's demo story,
running on the new stack.

---

## Phase 3 — Screen 3 (Regulatory Reporting)

- [ ] Report calendar (status: Not started → Draft → Under review → Approved → Submitted, coloured
  by urgency)
- [ ] Regulator-format report view (capital adequacy return as the first template)
- [ ] Drill-to-source: `calculation_audit` table populated alongside every calculated figure
  (formula text, source tables, filters, record count, timestamp) — this is the single feature
  the source doc calls out as mattering most to bankers/auditors
- [ ] Validation checks (`validation_rules` table) — block/warn/info severities
- [ ] PDF export (ReportLab) and Excel export (openpyxl) — test both thoroughly; a broken export
  button is explicitly called out as a deal-loser in the source doc

**Exit criteria:** a capital adequacy report can be opened, every line drilled to its source, and
exported to both PDF and Excel in the regulator's layout.

---

## Phase 4 — Screens 2 & 5 (Credit Risk, Branch/Segment Performance)

- [ ] **Screen 2 — Portfolio & Credit Risk**: loan book sliced by product/segment/branch/currency
  (each with total + bad-loan bars), 24-month NPL trend by product, IFRS 9 staging table + stage
  migration chart, top-20 exposures with %-of-capital, ageing table, LTV distribution
- [ ] **Screen 5 — Branch & Segment Performance**: branch league table, regional rollup, segment/
  product performance (net contribution = interest income − provisions), channel usage mix,
  efficiency quadrant scatter
  - Precompute `branch_performance_monthly` nightly — do not join branches→customers→accounts/loans
    live on page load

**Exit criteria:** both screens load in under ~2 seconds against the synthetic dataset and
correctly surface at least one clear "story" (e.g. one product driving NPL trend, one branch
losing money) for the demo narrative.

---

## Phase 5 — Screen 4 (Scenario Modelling)

Built last since it depends on stable figures from Screens 1-2 (capital, RWA, liquidity) to stress.

- [ ] In-memory snapshot on screen load (~50 numbers: loans by currency/product/rate-type, capital,
  liquidity, deposits by type) — sliders recompute against this snapshot in the browser, never
  querying the database per slider movement
- [ ] Four sliders (devaluation 0-50%, rate change ±5%, NPL increase 0-15%, deposit outflow 0-30%)
  with Base/Adverse/Severe presets
- [ ] Calculation order per the source doc: devaluation → revalue book → extra defaults it causes →
  independent NPL stress → new provisions → rate effects on profit → reduce capital → recompute
  RWA → recompute capital ratio → separately recompute liquidity
- [ ] Waterfall chart (today's ratio → each stressed factor → final ratio) and 12-month projection
  with the regulatory-minimum crossing point highlighted
- [ ] Assumptions stored in a settings table with a visible "Assumptions" link — not hardcoded

**Exit criteria:** moving a slider updates every downstream number with no visible delay, and the
waterfall chart correctly attributes impact across the four stress factors.

---

## Phase 6 — Integration, Polish, Demo Prep

- [ ] End-to-end rehearsal: Databricks notebooks run → exceptions flow into Postgres → officer
  resolves a case in Screen 6 → Screen 1/3 reflect the resolution → audit trail shows the full
  history
- [ ] Threshold/colour settings table tuned per-metric (red/amber/green cutoffs, since every
  regulator's floor differs)
- [ ] PDF/Excel export dry run under demo conditions
- [ ] Fix rough edges, freeze the demo environment

---

## Open Decisions to Revisit

- **Synthetic data scale**: source doc mentions "two million transactions" for performance-proofing
  the precomputed-summary approach — confirm with the user whether the demo needs that scale or a
  much smaller illustrative dataset is enough.
- **Hosting**: FastAPI + PostgreSQL + React need an actual deployment target (Azure App Service,
  AKS, or just local/dev for the demo) — not yet decided.
- **Auth**: seeded demo users are fine for a demo; note if the client will eventually need real SSO
  (Keycloak, per the source doc).
