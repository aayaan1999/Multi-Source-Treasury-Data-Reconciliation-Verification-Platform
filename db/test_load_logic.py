"""Tests the merge logic of notebooks/load_to_postgres.py against a real, throwaway PostgreSQL.

Runs the notebook's own `MERGE HELPERS` cell (no copy of the logic), against db/schema.sql, using
hand-built staging tables shaped like the ones Spark's JDBC writer creates.

    pip install pgserver psycopg2-binary
    python db/test_load_logic.py
"""
import os
import pathlib
import tempfile
from datetime import date, datetime

import pgserver
import psycopg2
import psycopg2.errors

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Pull the helper cell straight out of the notebook so the test exercises the shipped code.
cells = (ROOT / "notebooks" / "load_to_postgres.py").read_text(encoding="utf-8").split("\n# COMMAND ----------\n")
helper_src = next(c for c in cells if "# MERGE HELPERS" in c)
ns = {}
exec(helper_src, ns)
run_merge = ns["run_merge"]

srv = pgserver.get_server(pathlib.Path(tempfile.mkdtemp(prefix="pgdata_")), cleanup_mode="stop")
conn = psycopg2.connect(srv.get_uri())
conn.autocommit = True
cur = conn.cursor()
cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


def stage(tables):
    """Recreate the staging schema. tables = {name: (column DDL, rows)}."""
    cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    cur.execute("CREATE SCHEMA staging")
    for name, (ddl, rows) in tables.items():
        cur.execute(f"CREATE TABLE staging.{name} ({ddl})")
        if rows:
            marks = ",".join(["%s"] * len(rows[0]))
            cur.executemany(f"INSERT INTO staging.{name} VALUES ({marks})", rows)


def merge():
    """Run the merge in one transaction like the notebook does."""
    conn.autocommit = False
    try:
        with conn.cursor() as c:
            written = run_merge(c)
        conn.commit()
        return written
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def scalar(sql, *args):
    cur.execute(sql, args)
    return cur.fetchone()[0]


BRANCH = ("branch_id text, name text, region text, staff_count double precision, monthly_opex double precision")
CUSTOMER = ("customer_id text, name text, segment text, branch_id text, onboard_date date, risk_rating text, country text")
ACCOUNT = ("account_id text, customer_id text, type text, currency text, balance double precision, open_date date")
LOAN = ("loan_id text, customer_id text, product text, principal double precision, outstanding double precision, "
        "currency text, interest_rate double precision, origination_date date, maturity_date date, "
        "days_past_due double precision, stage double precision, provision_amount double precision, collateral_value double precision")
TXN = "transaction_id text, account_id text, date date, amount double precision, currency text, type text, channel text"
KPI = "calculation_date date, car_pct double precision, assumptions_applied text[]"
SCEN = "calculation_date date, loans_by_currency text, tier1_capital_usd double precision"
DQ = "source_table text, record_key text, flag_label text, description text"
FLAG = "transaction_id text, flag_label text, flag_type text, description text, status text, detected_at timestamp"
FXLOG = ("notebook_run_id text, currency_pair text, rate double precision, fetched_at text, "
         "used_in_calculation text, logged_at timestamp")

d1, d2 = date(2026, 9, 20), date(2026, 9, 21)
ts = datetime(2026, 9, 21, 8, 0, 0)

# ---- Load 1: everything, first time ----------------------------------------------------------
stage({
    "branches": (BRANCH, [("B1", "Beirut", "Lebanon", 10.0, 5000.0), ("B2", "Riyadh", "KSA", 8.0, 4000.0)]),
    "customers": (CUSTOMER, [("C1", "Ann", "Retail", "B1", date(2020, 1, 1), "Low", "LB"),
                             ("C2", "Bob", "SME", "B2", date(2021, 2, 2), "Med", "SA")]),
    "accounts": (ACCOUNT, [("A1", "C1", "Savings", "USD", 100.0, date(2020, 1, 1)),
                           ("A2", "C2", "Current", "SAR", 200.0, date(2021, 2, 2))]),
    "loans": (LOAN, [("L1", "C1", "Mortgage", 1000.0, 900.0, "USD", 5.5, date(2020, 1, 1), date(2030, 1, 1), 0.0, 1.0, 10.0, 1200.0)]),
    "transactions": (TXN, [("T1", "A1", date(2026, 9, 1), 60000.0, "USD", "Deposit", "Branch"),
                           ("T2", "A2", date(2026, 9, 2), 10.5, "SAR", "Withdrawal", "ATM")]),
    "kpi_daily_summary": (KPI, [(d1, 12.5, ["DEPOSIT_RATE_BY_TYPE placeholder"])]),
    "scenario_snapshot": (SCEN, [(d1, '{"USD": 900.0, "SAR": 50.0}', 100.0)]),
    "data_quality_exceptions": (DQ, [("customers", "C9", "MISSING_RISK_RATING", "risk_rating is missing"),
                                     ("loans", "L9", "INVALID_STAGE", "stage 5"),
                                     ("capital_positions", "(no key #1)", "MISSING_MONTH", "month is missing")]),
    "flagged_transactions": (FLAG, [("T1", "LARGE_AMOUNT", "THRESHOLD", "60000 USD", "PENDING_REVIEW", ts)]),
    "fx_rate_usage_log": (FXLOG, [("run1", "USD/LBP", 89500.0, "2026-09-21T08:00:00", "kpi", ts)]),
})
w = merge()
check("load 1: entity rows written", w["branches"] == 2 and w["customers"] == 2 and w["accounts"] == 2
      and w["loans"] == 1 and w["transactions"] == 2, str(w))
check("load 1: loans.stage cast to smallint", scalar("SELECT stage FROM loans") == 1)
check("load 1: double -> numeric(20,4)", float(scalar("SELECT balance FROM accounts WHERE account_id='A1'")) == 100.0)
check("load 1: text[] column loaded", scalar("SELECT assumptions_applied[1] FROM kpi_daily_summary") == "DEPOSIT_RATE_BY_TYPE placeholder")
check("load 1: JSON text cast to jsonb and queryable",
      float(scalar("SELECT (loans_by_currency->>'USD')::float FROM scenario_snapshot")) == 900.0)
check("load 1: exceptions loaded incl. no-key placeholder", scalar("SELECT count(*) FROM data_quality_exceptions") == 3)
check("load 1: exception_id auto-assigned", scalar("SELECT count(exception_id) FROM data_quality_exceptions") == 3)
check("load 1: flagged row inserted as PENDING_REVIEW", scalar("SELECT status FROM flagged_transactions") == "PENDING_REVIEW")
check("load 1: fx usage log loaded", scalar("SELECT count(*) FROM fx_rate_usage_log") == 1)

# ---- Load 2: reviewer action must survive; stale exceptions go; history kept -----------------
cur.execute("UPDATE flagged_transactions SET status='APPROVED' WHERE transaction_id='T1'")
e1_id = scalar("SELECT exception_id FROM data_quality_exceptions WHERE record_key='C9'")
stage({
    "branches": (BRANCH, [("B1", "Beirut", "Lebanon", 10.0, 5000.0)]),
    "customers": (CUSTOMER, [("C1", "Ann", "Retail", "B1", date(2020, 1, 1), "Low", "LB")]),
    "accounts": (ACCOUNT, [("A1", "C1", "Savings", "USD", 150.0, date(2020, 1, 1))]),
    "loans": (LOAN, []),
    "transactions": (TXN, [("T1", "A1", date(2026, 9, 1), 60000.0, "USD", "Deposit", "Branch")]),
    "kpi_daily_summary": (KPI, [(d2, 13.0, ["x"])]),
    "data_quality_exceptions": (DQ, [("customers", "C9", "MISSING_RISK_RATING", "updated text"),
                                     ("accounts", "A9", "NEGATIVE_BALANCE", "new one")]),
    "flagged_transactions": (FLAG, [("T1", "LARGE_AMOUNT", "THRESHOLD", "60000 USD", "PENDING_REVIEW", ts),
                                    ("T2", "DUPLICATE_TRANSACTION", "OPERATIONAL", "dup", "PENDING_REVIEW", ts)]),
})
w = merge()
check("load 2: reviewed status NOT overwritten",
      scalar("SELECT status FROM flagged_transactions WHERE transaction_id='T1'") == "APPROVED")
check("load 2: new flagged row inserted; only 1 written", scalar("SELECT status FROM flagged_transactions WHERE transaction_id='T2'") == "PENDING_REVIEW" and w["flagged_transactions"] == 1)
check("load 2: entity full refresh removed dropped rows",
      scalar("SELECT count(*) FROM branches") == 1 and scalar("SELECT count(*) FROM customers") == 1
      and scalar("SELECT count(*) FROM loans") == 0 and scalar("SELECT count(*) FROM transactions") == 1)
check("load 2: updated value refreshed", float(scalar("SELECT balance FROM accounts")) == 150.0)
check("load 2: persisting exception keeps its exception_id, description updated",
      scalar("SELECT exception_id FROM data_quality_exceptions WHERE record_key='C9'") == e1_id
      and scalar("SELECT description FROM data_quality_exceptions WHERE record_key='C9'") == "updated text")
check("load 2: stale exceptions deleted, new one added",
      scalar("SELECT count(*) FROM data_quality_exceptions") == 2
      and scalar("SELECT count(*) FROM data_quality_exceptions WHERE record_key='A9'") == 1)
check("load 2: KPI history kept (2 dates)", scalar("SELECT count(*) FROM kpi_daily_summary") == 2)
check("load 2: tables not staged are untouched", scalar("SELECT count(*) FROM scenario_snapshot") == 1
      and scalar("SELECT count(*) FROM fx_rate_usage_log") == 1)

# ---- Load 3: reloading the same date replaces, not duplicates --------------------------------
stage({"kpi_daily_summary": (KPI, [(d2, 99.0, ["y"])])})
merge()
check("load 3: same calculation_date replaced, not duplicated",
      scalar("SELECT count(*) FROM kpi_daily_summary") == 2 and scalar("SELECT car_pct FROM kpi_daily_summary WHERE calculation_date=%s", d2) == 99.0)

# ---- Load 4: bad data must fail loudly and leave everything as it was (atomic) ---------------
before = (scalar("SELECT count(*) FROM customers"), scalar("SELECT count(*) FROM accounts"), scalar("SELECT balance FROM accounts"))
stage({
    "branches": (BRANCH, [("B1", "Beirut", "Lebanon", 10.0, 5000.0)]),
    "customers": (CUSTOMER, [("C1", "Ann", "Retail", "B1", date(2020, 1, 1), "Low", "LB")]),
    "accounts": (ACCOUNT, [("A1", "C1", "Savings", "USD", 999.0, date(2020, 1, 1)),
                           ("A7", "C_MISSING", "Savings", "USD", 1.0, date(2020, 1, 1))]),
})
try:
    merge()
    check("load 4: orphan child rejected by foreign key", False, "merge succeeded")
except psycopg2.errors.ForeignKeyViolation:
    check("load 4: orphan child rejected by foreign key", True)
after = (scalar("SELECT count(*) FROM customers"), scalar("SELECT count(*) FROM accounts"), scalar("SELECT balance FROM accounts"))
check("load 4: failed load rolled back completely (nothing half-applied)", before == after, f"{before} vs {after}")

# ---- Report ---------------------------------------------------------------------------------
for name, ok, detail in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
