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

# ---- Load 5: source tags (specs/source-tagging.md) land, and persisting exceptions refresh them
TAGS = ", source_system text, source_country text, ingest_batch_id text, source_file text"
tag1 = ("CORE_CSV", "Lebanon", "CORE_CSV-20260924T100000Z-aaaa1111", "customers.csv")
tag2 = ("CORE_CSV", "Lebanon", "CORE_CSV-20260925T100000Z-bbbb2222", "customers.csv")
stage({
    "branches": (BRANCH + TAGS, [("B1", "Beirut", "Beirut", 10.0, 5000.0, "CORE_CSV", "Lebanon", tag1[2], "branches.csv")]),
    "customers": (CUSTOMER + TAGS, [("C1", "Ann", "Retail", "B1", date(2020, 1, 1), "Low", "Lebanon") + tag1]),
    # Children staged untagged: tags are optional per table, and the full refresh needs the chain.
    "accounts": (ACCOUNT, [("A1", "C1", "Savings", "USD", 150.0, date(2020, 1, 1))]),
    "transactions": (TXN, [("T1", "A1", date(2026, 9, 1), 60000.0, "USD", "Deposit", "Branch")]),
    "data_quality_exceptions": (DQ + TAGS, [("customers", "C9", "MISSING_RISK_RATING", "risk_rating is missing") + tag1]),
})
merge()
check("load 5: entity row carries its source tags",
      scalar("SELECT source_system || '|' || source_country || '|' || ingest_batch_id || '|' || source_file FROM customers WHERE customer_id='C1'")
      == "|".join(tag1))
check("load 5: customer's own country kept separate from source_country",
      scalar("SELECT country FROM customers WHERE customer_id='C1'") == "Lebanon"
      and scalar("SELECT source_file FROM branches WHERE branch_id='B1'") == "branches.csv")
e9 = scalar("SELECT exception_id FROM data_quality_exceptions WHERE record_key='C9'")
stage({"data_quality_exceptions": (DQ + TAGS, [("customers", "C9", "MISSING_RISK_RATING", "risk_rating is missing") + tag2])})
merge()
check("load 5: persisting exception keeps its id, tags refreshed to the latest run",
      scalar("SELECT exception_id FROM data_quality_exceptions WHERE record_key='C9'") == e9
      and scalar("SELECT ingest_batch_id FROM data_quality_exceptions WHERE record_key='C9'") == tag2[2])
stage({"data_quality_exceptions": (DQ, [("customers", "C9", "MISSING_RISK_RATING", "untagged run")])})
merge()
check("load 5: an untagged (older Notebook 2) load still works",
      scalar("SELECT description FROM data_quality_exceptions WHERE record_key='C9'") == "untagged run")

# ---- Load 6: pipeline reconciliation items (specs/pipeline-reconciliation.md) are insert-only --
PREC = ("recon_key text, ingest_batch_id text, source_system text, source_country text, source_table text, "
        "received_rows bigint, clean_rows bigint, rejected_rows bigint, amount_column text, "
        "unreadable_amount_rows bigint, amounts_by_currency text, has_gap boolean, status text, detected_at timestamp")
item = ("R1|CORE_CSV|Lebanon|transactions", "R1", "CORE_CSV", "Lebanon", "transactions", 6, 5, 1, "amount", 0,
        '{"USD": {"received": 64800.0, "clean": 63800.0, "gap": 1000.0}}', True, "OPEN", ts)
stage({"pipeline_reconciliation": (PREC, [item])})
w = merge()
check("load 6: item loaded, amounts queryable as jsonb",
      w["pipeline_reconciliation"] == 1
      and float(scalar("SELECT (amounts_by_currency->'USD'->>'gap')::float FROM pipeline_reconciliation")) == 1000.0)
cur.execute("ALTER TABLE pipeline_reconciliation DROP CONSTRAINT pipeline_reconciliation_status_check")
cur.execute("UPDATE pipeline_reconciliation SET status = 'IN_REVIEW'")   # as FLOW-5 will
stage({"pipeline_reconciliation": (PREC, [item, ("R2|CORE_CSV|Lebanon|transactions", "R2") + item[2:]])})
w = merge()
check("load 6: rerun adds only the new run's item and keeps the app-set status",
      w["pipeline_reconciliation"] == 1 and scalar("SELECT count(*) FROM pipeline_reconciliation") == 2
      and scalar("SELECT status FROM pipeline_reconciliation WHERE ingest_batch_id='R1'") == "IN_REVIEW")
cur.execute("DROP TABLE pipeline_reconciliation CASCADE")   # corrections (migration 009) depend on it
stage({"pipeline_reconciliation": (PREC, [item])})
w = merge()
check("load 6: skipped, not failed, before migration 008 creates the table", "pipeline_reconciliation" not in w)

# ---- Load 7: corrections Notebook 1 applied are marked synced, once (spec cfo-reconciliation-workflow 7)
cur.execute("INSERT INTO roles (name) VALUES ('approver') RETURNING role_id")
role = cur.fetchone()[0]
cur.execute("INSERT INTO users (name, email, role_id) VALUES ('CFO', 'cfo@x', %s) RETURNING user_id", (role,))
cfo = cur.fetchone()[0]
cur.execute("""INSERT INTO reconciliation_corrections (recon_id, source_table, record_key, field_name, old_value, new_value,
               entered_by, status) VALUES (1, 'transactions', 'T0009', 'channel', 'Cheque', 'Branch', %s, 'APPROVED'),
               (1, 'transactions', 'T0010', 'account_id', 'ACC999', 'ACC001', %s, 'APPROVED') RETURNING correction_id""", (cfo, cfo))
c1, c2 = [r[0] for r in cur.fetchall()]
APPLIED = "correction_id bigint, source_table text, record_key text, field_name text, ingest_batch_id text, applied_at timestamp"
stage({"applied_corrections": (APPLIED, [(c1, "transactions", "T0009", "channel", "R1", ts)])})
w = merge()
first = scalar("SELECT synced_at FROM reconciliation_corrections WHERE correction_id = %s", c1)
check("load 7: an applied correction is marked synced, the other isn't",
      w["applied_corrections"] == 1 and first is not None
      and scalar("SELECT synced_at FROM reconciliation_corrections WHERE correction_id = %s", c2) is None)
stage({"applied_corrections": (APPLIED, [(c1, "transactions", "T0009", "channel", "R2", ts)])})
w = merge()
check("load 7: re-applied on a later run, synced_at keeps the first time",
      w["applied_corrections"] == 0 and scalar("SELECT synced_at FROM reconciliation_corrections WHERE correction_id = %s", c1) == first)

# ---- Load 8: a snapshot table Neon doesn't have yet is skipped, not failed ---------------------
COUNTRY = ("calculation_date date, country text, customer_count bigint, deposits_usd double precision, "
           "loans_usd double precision, npl_loans_usd double precision, npl_ratio_pct double precision, "
           "transaction_count bigint, transaction_volume_usd double precision")
stage({"country_performance_summary": (COUNTRY, [(d2, "Lebanon", 5, 100.0, 900.0, 90.0, 10.0, 6, 70000.0)])})
w = merge()
check("load 8: country view loaded like the other snapshots",
      w["country_performance_summary"] == 1 and scalar("SELECT npl_ratio_pct FROM country_performance_summary") == 10.0)
cur.execute("DROP TABLE country_performance_summary")
stage({"country_performance_summary": (COUNTRY, [(d2, "Lebanon", 5, 100.0, 900.0, 90.0, 10.0, 6, 70000.0)]),
       "kpi_daily_summary": (KPI, [(d2, 14.0, ["z"])])})
w = merge()
check("load 8: before its migration the new table is skipped and the rest still loads",
      "country_performance_summary" not in w and scalar("SELECT car_pct FROM kpi_daily_summary WHERE calculation_date=%s", d2) == 14.0)

# ---- Load 9: core-system breaks - no duplicates, seen-again refresh, recurring reopen ---------
REX = ("source_system text, entity_type text, entity_id text, field_name text, source_value text, canonical_value text, "
       "mismatch_type text, status text, detected_at timestamp, resolved_by text, resolved_at timestamp, "
       "resolution_note text, resolved_rule text, first_seen timestamp, last_seen timestamp, times_seen integer")
t1, t2 = datetime(2026, 9, 23, 6), datetime(2026, 9, 24, 6)
def rex(eid, field, mismatch, last_seen, times, status="OPEN", rule=None):
    return ("neon", "account", eid, field, "1015", "1000", mismatch, status, t1, None, None, None, rule, t1, last_seen, times)
stage({"reconciliation_exceptions": (REX, [rex("A1", "balance", "VALUE_MISMATCH", t1, 1),
                                           rex("A2", None, "MISSING_IN_SOURCE", t1, 1),
                                           rex("A3", "name", "VALUE_MISMATCH", t1, 1, "AUTO_ACCEPTED", "FORMATTING_ONLY")])})
merge()
cur.execute("UPDATE reconciliation_exceptions SET status = 'ACCEPTED', resolved_at = %s WHERE entity_id = 'A1'", (datetime(2026, 9, 23, 12),))
cur.execute("UPDATE reconciliation_exceptions SET resolved_at = %s WHERE entity_id = 'A3'", (datetime(2026, 9, 23, 12),))
stage({"reconciliation_exceptions": (REX, [rex("A1", "balance", "VALUE_MISMATCH", t2, 2),
                                           rex("A2", None, "MISSING_IN_SOURCE", t2, 2),
                                           rex("A3", "name", "VALUE_MISMATCH", t2, 2, "AUTO_ACCEPTED", "FORMATTING_ONLY")])})
merge()
check("load 9: a missing-record break (no field) is never inserted twice",
      scalar("SELECT count(*) FROM reconciliation_exceptions WHERE entity_id = 'A2'") == 1)
check("load 9: a resolved break seen again is reopened and marked recurring",
      scalar("SELECT status || '/' || recurring || '/' || times_seen FROM reconciliation_exceptions WHERE entity_id = 'A1'") == "OPEN/true/2")
check("load 9: an auto-cleared break stays cleared (its formatting difference persists by nature)",
      scalar("SELECT status || '/' || recurring FROM reconciliation_exceptions WHERE entity_id = 'A3'") == "AUTO_ACCEPTED/false")

# ---- Report ---------------------------------------------------------------------------------
for name, ok, detail in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
