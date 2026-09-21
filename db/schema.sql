-- PostgreSQL schema for the application layer (specs/postgres-schema.md).
-- Load order matters: entity tables -> time series -> Databricks Gold imports -> workflow/reporting.
-- Column names for sections 1-3 mirror the Databricks {table}_clean / Gold output shapes exactly,
-- so the nightly import job has no rename step. Section 4-5 columns come from
-- "Middle East bank data cleaning and reporting.md" (database section); where that doc only names
-- a table's purpose (report_*, risk_weights, validation_rules, calculation_audit, submitted_files)
-- the columns below are inferred and flagged INFERRED.

BEGIN;

-- ---------------------------------------------------------------------------------------------
-- 1. Entity tables (mirror Notebook 2's *_clean output)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE branches (
    branch_id     text PRIMARY KEY,
    name          text NOT NULL,
    region        text NOT NULL,
    staff_count   integer,
    monthly_opex  numeric(20,4)
);

CREATE TABLE customers (
    customer_id   text PRIMARY KEY,
    name          text NOT NULL,
    segment       text NOT NULL CHECK (segment IN ('Retail', 'SME', 'Corporate')),
    branch_id     text NOT NULL REFERENCES branches (branch_id),
    onboard_date  date,
    risk_rating   text NOT NULL,
    country       text
);

CREATE TABLE accounts (
    account_id   text PRIMARY KEY,
    customer_id  text NOT NULL REFERENCES customers (customer_id),
    type         text NOT NULL,
    currency     text NOT NULL,
    balance      numeric(20,4),
    open_date    date
);

CREATE TABLE loans (
    loan_id           text PRIMARY KEY,
    customer_id       text NOT NULL REFERENCES customers (customer_id),
    product           text NOT NULL,
    principal         numeric(20,4),
    outstanding       numeric(20,4),
    currency          text NOT NULL,
    interest_rate     double precision,
    origination_date  date,
    maturity_date     date,
    days_past_due     integer,
    stage             smallint CHECK (stage IN (1, 2, 3)),
    provision_amount  numeric(20,4),
    collateral_value  numeric(20,4)
);

CREATE INDEX loans_customer_idx ON loans (customer_id);

-- ---------------------------------------------------------------------------------------------
-- 2. Time-series tables
-- ---------------------------------------------------------------------------------------------

CREATE TABLE transactions (
    transaction_id  text PRIMARY KEY,
    account_id      text NOT NULL REFERENCES accounts (account_id),
    date            date NOT NULL,
    amount          numeric(20,4) NOT NULL,
    currency        text NOT NULL,
    type            text,
    channel         text
);

-- Screens 1/2/5 read precomputed Gold tables, not this one, but the date index keeps drill-downs fast.
CREATE INDEX transactions_account_date_idx ON transactions (account_id, date);

CREATE TABLE capital_positions (
    month                text PRIMARY KEY CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    tier1_capital        numeric(20,4),
    tier2_capital        numeric(20,4),
    risk_weighted_assets numeric(20,4)
);

CREATE TABLE liquidity_daily (
    date              date PRIMARY KEY,
    hqla              numeric(20,4),
    net_outflows_30d  numeric(20,4),
    stable_funding    numeric(20,4),
    required_funding  numeric(20,4)
);

-- One rate per day per pair. specs/postgres-schema.md 2.2 says to mirror `fx_rates_live`, but
-- specs/fx-realtime-ingestion.md removed that table (FX is a live utility call, not ingested data);
-- the audit record of rates actually used is fx_rate_usage_log below.
CREATE TABLE fx_rates (
    date           date NOT NULL,
    currency_pair  text NOT NULL,
    rate           double precision NOT NULL,
    PRIMARY KEY (date, currency_pair)
);

CREATE TABLE fx_rate_usage_log (
    notebook_run_id      text NOT NULL,
    currency_pair        text NOT NULL,
    rate                 double precision NOT NULL,
    fetched_at           text NOT NULL,
    used_in_calculation  text NOT NULL,
    logged_at            timestamptz NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- 3. Gold / Silver-enrichment import tables (from the nightly Databricks job)
--    Shapes are 1:1 with what notebooks 3, 4, 5 and 6 actually write (calculation_date included
--    even where the notebook spec's column table omits it).
-- ---------------------------------------------------------------------------------------------

CREATE TABLE kpi_daily_summary (
    calculation_date         date PRIMARY KEY,
    car_pct                  double precision,
    lcr_pct                  double precision,
    npl_ratio_pct            double precision,
    total_assets_usd         double precision,
    dollarization_ratio_pct  double precision,
    nim_pct                  double precision,
    cost_to_income_pct       double precision,
    roe_pct                  double precision,
    assumptions_applied      text[]
);

-- Notebook 2's shared exceptions log. exception_id is app-side only (Screen 6 needs a stable handle
-- to reference an exception); the import job loads the four Databricks columns and lets it default.
CREATE TABLE data_quality_exceptions (
    exception_id  bigserial PRIMARY KEY,
    source_table  text NOT NULL,
    record_key    text NOT NULL,
    flag_label    text NOT NULL,
    description   text,
    UNIQUE (source_table, record_key, flag_label)
);

-- status is mutable (updated by review outcomes); everything else is written once by Notebook 5.
CREATE TABLE flagged_transactions (
    transaction_id  text NOT NULL,
    flag_label      text NOT NULL CHECK (flag_label IN
                        ('LARGE_AMOUNT', 'VELOCITY_BREACH', 'STRUCTURING_PATTERN', 'DUPLICATE_TRANSACTION')),
    flag_type       text NOT NULL CHECK (flag_type IN ('FRAUD', 'FAULT')),
    description     text,
    status          text NOT NULL DEFAULT 'PENDING_REVIEW',
    detected_at     timestamptz NOT NULL,
    PRIMARY KEY (transaction_id, flag_label)
);

CREATE TABLE exception_summary_by_flag (
    calculation_date  date NOT NULL,
    source_table      text NOT NULL,
    flag_label        text NOT NULL,
    exception_count   bigint NOT NULL,
    PRIMARY KEY (calculation_date, source_table, flag_label)
);

CREATE TABLE exception_summary_by_table (
    calculation_date      date NOT NULL,
    source_table          text NOT NULL,
    raw_row_count         bigint NOT NULL,
    flagged_record_count  bigint NOT NULL,
    exception_rate_pct    double precision,
    PRIMARY KEY (calculation_date, source_table)
);

CREATE TABLE loan_breakdown_by_dimension (
    calculation_date          date NOT NULL,
    dimension_type            text NOT NULL CHECK (dimension_type IN ('product', 'segment', 'branch', 'currency')),
    dimension_value           text NOT NULL,
    total_outstanding_usd     double precision,
    bad_loan_outstanding_usd  double precision,
    PRIMARY KEY (calculation_date, dimension_type, dimension_value)
);

CREATE TABLE loan_stage_summary (
    calculation_date  date NOT NULL,
    stage             smallint NOT NULL,
    loan_count        bigint,
    outstanding_usd   double precision,
    provisions_usd    double precision,
    coverage_pct      double precision,
    PRIMARY KEY (calculation_date, stage)
);

CREATE TABLE top_exposures (
    calculation_date  date NOT NULL,
    customer_id       text NOT NULL,
    customer_name     text,
    outstanding_usd   double precision,
    product           text,
    days_past_due     integer,
    pct_of_capital    double precision,
    PRIMARY KEY (calculation_date, customer_id)
);

CREATE TABLE loan_ageing_summary (
    calculation_date  date NOT NULL,
    bucket            text NOT NULL,
    outstanding_usd   double precision,
    pct_of_book       double precision,
    PRIMARY KEY (calculation_date, bucket)
);

CREATE TABLE ltv_distribution (
    calculation_date  date NOT NULL,
    bucket            text NOT NULL,
    outstanding_usd   double precision,
    loan_count        bigint,
    PRIMARY KEY (calculation_date, bucket)
);

CREATE TABLE branch_performance_summary (
    calculation_date      date NOT NULL,
    branch_id             text NOT NULL,
    region                text,
    deposits_usd          double precision,
    loans_usd             double precision,
    revenue_usd           double precision,
    cost_usd              double precision,
    profit_usd            double precision,
    cost_to_income_pct    double precision,
    staff_count           integer,
    profit_per_staff_usd  double precision,
    PRIMARY KEY (calculation_date, branch_id)
);

CREATE TABLE segment_performance_summary (
    calculation_date          date NOT NULL,
    segment                   text NOT NULL,
    customer_count            bigint,
    deposits_usd              double precision,
    loans_usd                 double precision,
    revenue_usd               double precision,
    bad_loans_usd             double precision,
    profit_usd                double precision,
    revenue_per_customer_usd  double precision,
    PRIMARY KEY (calculation_date, segment)
);

CREATE TABLE product_performance_summary (
    calculation_date      date NOT NULL,
    product               text NOT NULL,
    outstanding_usd       double precision,
    avg_interest_rate     double precision,
    interest_income_usd   double precision,
    npl_pct               double precision,
    net_contribution_usd  double precision,
    PRIMARY KEY (calculation_date, product)
);

-- Single row per day; Databricks map<string,double> columns land as jsonb.
CREATE TABLE scenario_snapshot (
    calculation_date          date PRIMARY KEY,
    loans_by_currency         jsonb,
    loans_by_product          jsonb,
    loans_by_rate_type        jsonb,
    deposits_by_type          jsonb,
    deposits_by_rate_type     jsonb,
    tier1_capital_usd         double precision,
    tier2_capital_usd         double precision,
    risk_weighted_assets_usd  double precision,
    hqla_usd                  double precision,
    net_outflows_30d_usd      double precision,
    stable_funding_usd        double precision,
    required_funding_usd      double precision,
    current_npl_pct           double precision,
    current_coverage_pct      double precision,
    current_avg_interest_rate double precision
);

-- ---------------------------------------------------------------------------------------------
-- 4. Users, roles and workflow (Screen 6).
--    workflow_* and tasks are a READ-SIDE MIRROR of Camunda 8 state (specs/postgres-schema.md 2.4);
--    Zeebe/Tasklist is authoritative for "is this task still open".
-- ---------------------------------------------------------------------------------------------

CREATE TABLE roles (
    role_id      serial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    permissions  jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE users (
    user_id     serial PRIMARY KEY,
    name        text NOT NULL,
    email       text NOT NULL UNIQUE,
    role_id     integer NOT NULL REFERENCES roles (role_id),
    department  text,
    -- Demo login only (specs/fastapi-backend.md section 3); set by backend/seed_demo_users.py.
    password_hash text
);

-- INFERRED: source doc lists purpose only ("name, frequency, due-day rule, owner").
CREATE TABLE report_definitions (
    report_id      serial PRIMARY KEY,
    name           text NOT NULL UNIQUE,
    regulator      text,
    frequency      text NOT NULL,
    due_day_rule   text,
    owner_role_id  integer REFERENCES roles (role_id)
);

-- INFERRED: "which report, which period, status, owner, dates, submitted timestamp".
CREATE TABLE report_instances (
    report_instance_id  serial PRIMARY KEY,
    report_id           integer NOT NULL REFERENCES report_definitions (report_id),
    period              text NOT NULL,
    status              text NOT NULL DEFAULT 'DRAFT',
    owner_user_id       integer REFERENCES users (user_id),
    due_date            date,
    created_at          timestamptz NOT NULL DEFAULT now(),
    submitted_at        timestamptz,
    UNIQUE (report_id, period)
);

-- INFERRED: one row per figure on the regulator form; line_code (e.g. 'B.1') is what comments and
-- calculation_audit hang off.
CREATE TABLE report_line_items (
    report_instance_id  integer NOT NULL REFERENCES report_instances (report_instance_id),
    line_code           text NOT NULL,
    label               text NOT NULL,
    value               numeric(24,4),
    prior_value         numeric(24,4),
    explanation         text,
    PRIMARY KEY (report_instance_id, line_code)
);

-- INFERRED: "formula text, source tables, filters applied, record count, timestamp".
CREATE TABLE calculation_audit (
    audit_id            bigserial PRIMARY KEY,
    report_instance_id  integer NOT NULL,
    line_code           text NOT NULL,
    formula_text        text NOT NULL,
    source_tables       text[] NOT NULL,
    filters_applied     text,
    record_count        bigint,
    calculated_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (report_instance_id, line_code) REFERENCES report_line_items (report_instance_id, line_code)
);

-- INFERRED: "weights based on loan type and rating, changeable without touching code".
CREATE TABLE risk_weights (
    product       text NOT NULL,
    risk_rating   text NOT NULL DEFAULT '*',
    weight_pct    numeric(6,2) NOT NULL CHECK (weight_pct >= 0),
    PRIMARY KEY (product, risk_rating)
);

-- INFERRED: rules are data so new checks need no code release; expression is evaluated by the API.
CREATE TABLE validation_rules (
    rule_id      serial PRIMARY KEY,
    report_id    integer REFERENCES report_definitions (report_id),
    name         text NOT NULL,
    expression   text NOT NULL,
    severity     text NOT NULL CHECK (severity IN ('PASS_REQUIRED', 'COMMENT_REQUIRED', 'BLOCKING')),
    message      text
);

-- INFERRED: record of what was filed and in which regulator file format.
CREATE TABLE submitted_files (
    file_id             serial PRIMARY KEY,
    report_instance_id  integer NOT NULL REFERENCES report_instances (report_instance_id),
    file_format         text NOT NULL CHECK (file_format IN ('PDF', 'XLSX')),
    file_path           text NOT NULL,
    submitted_by        integer REFERENCES users (user_id),
    submitted_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workflow_steps (
    step_id        serial PRIMARY KEY,
    report_id      integer NOT NULL REFERENCES report_definitions (report_id),
    sequence       integer NOT NULL,
    role_required  integer NOT NULL REFERENCES roles (role_id),
    action_type    text NOT NULL,
    UNIQUE (report_id, sequence)
);

CREATE TABLE workflow_instances (
    instance_id         serial PRIMARY KEY,
    report_instance_id  integer NOT NULL REFERENCES report_instances (report_instance_id),
    current_step        integer REFERENCES workflow_steps (step_id),
    status              text NOT NULL,
    started_at          timestamptz NOT NULL DEFAULT now(),
    completed_at        timestamptz
);

-- camunda_task_id links the mirror row back to the authoritative Zeebe/Tasklist task.
CREATE TABLE tasks (
    task_id              serial PRIMARY KEY,
    workflow_instance_id integer REFERENCES workflow_instances (instance_id),
    camunda_task_id      text UNIQUE,
    assigned_to          integer REFERENCES users (user_id),
    task_type            text NOT NULL,
    status               text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    due_date             date,
    completed_at         timestamptz
);

CREATE TABLE comments (
    comment_id          serial PRIMARY KEY,
    report_instance_id  integer NOT NULL REFERENCES report_instances (report_instance_id),
    line_code           text,
    user_id             integer NOT NULL REFERENCES users (user_id),
    comment_text        text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    parent_comment_id   integer REFERENCES comments (comment_id)
);

CREATE TABLE limits (
    limit_id         serial PRIMARY KEY,
    metric_name      text NOT NULL UNIQUE,
    threshold_value  double precision NOT NULL,
    direction        text NOT NULL CHECK (direction IN ('ABOVE', 'BELOW')),
    owner_role       integer REFERENCES roles (role_id),
    resolution_days  integer NOT NULL
);

CREATE TABLE breaches (
    breach_id     serial PRIMARY KEY,
    limit_id      integer NOT NULL REFERENCES limits (limit_id),
    detected_at   timestamptz NOT NULL DEFAULT now(),
    actual_value  double precision NOT NULL,
    assigned_to   integer REFERENCES users (user_id),
    status        text NOT NULL DEFAULT 'OPEN',
    action_plan   text,
    resolved_at   timestamptz
);

-- Insert-only audit trail. The source doc says to "grant insert only, no update or delete"; a table
-- owner ignores grants, so a trigger enforces it regardless of who connects (superusers can still
-- disable triggers, which is acceptable for a POC).
CREATE TABLE audit_log (
    log_id       bigserial PRIMARY KEY,
    timestamp    timestamptz NOT NULL DEFAULT now(),
    user_id      integer REFERENCES users (user_id),
    action       text NOT NULL,
    object_type  text NOT NULL,
    object_id    text,
    old_value    text,
    new_value    text,
    ip_address   inet
);

CREATE INDEX audit_log_object_idx ON audit_log (object_type, object_id);
CREATE INDEX audit_log_user_idx ON audit_log (user_id, timestamp);

CREATE FUNCTION audit_log_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is insert-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_change();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_change();

-- ---------------------------------------------------------------------------------------------
-- 5. Sync and mapping tables
-- ---------------------------------------------------------------------------------------------

-- specs/bidirectional-sync.md: written by the Camunda service task, read back by Databricks over
-- JDBC. synced_at is the watermark column set by Databricks after it processes a row.
CREATE TABLE review_outcomes (
    outcome_id       bigserial PRIMARY KEY,
    record_type      text NOT NULL,
    source_table     text NOT NULL,
    record_key       text NOT NULL,
    outcome          text NOT NULL,
    corrected_value  jsonb,
    reviewed_by      integer REFERENCES users (user_id),
    reviewed_at      timestamptz NOT NULL DEFAULT now(),
    synced_at        timestamptz
);

CREATE INDEX review_outcomes_reviewed_at_idx ON review_outcomes (reviewed_at);

-- specs/multi-source-ingestion-adf.md section 8: shape defined now, population blocked on real
-- source-system code lists.
CREATE TABLE transaction_code_mapping (
    source_system     text NOT NULL,
    source_code       text NOT NULL,
    centralized_code  text NOT NULL,
    PRIMARY KEY (source_system, source_code)
);

COMMIT;

-- Row-level security is intentionally not defined here: specs/postgres-schema.md section 3 leaves it
-- blocked on a role-to-visibility model for the four seeded demo users.
