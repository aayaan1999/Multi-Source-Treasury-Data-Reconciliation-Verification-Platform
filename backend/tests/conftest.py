"""Test harness: a throwaway PostgreSQL (pgserver) with the real db/schema.sql, the demo users and a
small hand-built set of Gold/entity rows, and the real FastAPI app pointed at it."""
import os
import pathlib
import tempfile
from datetime import date

import pgserver
import psycopg2
import psycopg2.extras
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PASSWORD = "demo-pass-123"
D1, D2 = date(2026, 9, 20), date(2026, 9, 21)
TODAY = D2   # the "current date" the demo report calendar is seeded against


def _load_data(cur):
    def many(table, columns, rows):
        marks = ",".join(["%s"] * len(columns))
        cur.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})", rows)

    many("branches", ["branch_id", "name", "region", "staff_count", "monthly_opex"],
         [("B1", "Beirut", "Lebanon", 10, 5000), ("B2", "Riyadh", "KSA", 8, 4000)])
    many("customers", ["customer_id", "name", "segment", "branch_id", "risk_rating"],
         [("C1", "Ann", "Retail", "B1", "Low"), ("C2", "Bob", "SME", "B2", "Med"), ("C3", "Cy", "Corporate", "B1", "High")])
    many("loans", ["loan_id", "customer_id", "product", "currency", "principal", "outstanding", "days_past_due", "stage"],
         [("L1", "C1", "Mortgage", "USD", 1000, 900, 0, 1),
          ("L2", "C2", "SME Loan", "SAR", 500, 450, 45, 2),
          ("L3", "C3", "Corporate Loan", "USD", 2000, 1900, 120, 3),
          ("L4", "C1", "Personal Loan", "USD", 100, 80, 0, 1)])

    many("kpi_daily_summary", ["calculation_date", "car_pct", "nim_pct", "assumptions_applied"],
         [(D1, 12.0, 2.0, ["old"]), (D2, 13.5, 2.5, ["DEPOSIT_RATE_BY_TYPE placeholder (nim_pct)"])])

    breakdown = ["calculation_date", "dimension_type", "dimension_value", "total_outstanding_usd", "bad_loan_outstanding_usd"]
    many("loan_breakdown_by_dimension", breakdown,
         [(D1, "product", "OldProduct", 1.0, 0.0),
          (D2, "product", "Mortgage", 900.0, 0.0), (D2, "product", "Corporate Loan", 1900.0, 1900.0),
          (D2, "currency", "USD", 2880.0, 1900.0), (D2, "currency", "SAR", 450.0, 0.0)])
    many("loan_stage_summary", ["calculation_date", "stage", "loan_count", "outstanding_usd", "provisions_usd", "coverage_pct"],
         [(D2, 3, 1, 1900.0, 900.0, 47.4), (D2, 1, 2, 980.0, 10.0, 1.0), (D2, 2, 1, 450.0, 20.0, 4.4)])
    many("top_exposures", ["calculation_date", "customer_id", "customer_name", "outstanding_usd", "pct_of_capital"],
         [(D2, "C1", "Ann", 980.0, 10.0), (D2, "C3", "Cy", 1900.0, 20.0)])
    # inserted out of display order on purpose
    many("loan_ageing_summary", ["calculation_date", "bucket", "outstanding_usd", "pct_of_book"],
         [(D2, "180+", 5.0, 1.0), (D2, "Current", 900.0, 60.0), (D2, "90-180", 1900.0, 30.0), (D2, "31-60", 450.0, 9.0)])
    many("ltv_distribution", ["calculation_date", "bucket", "outstanding_usd", "loan_count"],
         [(D2, ">100%", 100.0, 1), (D2, "<50%", 500.0, 2), (D2, "80-100%", 300.0, 1), (D2, "50-80%", 200.0, 1)])
    many("branch_performance_summary", ["calculation_date", "branch_id", "region", "profit_usd"],
         [(D2, "B1", "Lebanon", 50.0), (D2, "B2", "KSA", 90.0)])
    many("segment_performance_summary", ["calculation_date", "segment", "profit_usd"],
         [(D2, "Retail", 10.0), (D2, "SME", 30.0)])
    many("product_performance_summary", ["calculation_date", "product", "net_contribution_usd"],
         [(D2, "Mortgage", 5.0), (D2, "SME Loan", 8.0)])
    many("accounts", ["account_id", "customer_id", "type", "currency", "balance"],
         [("A1", "C1", "Savings", "USD", 100), ("A2", "C2", "Current", "SAR", 200), ("A3", "C3", "Current", "USD", 300)])
    many("transactions", ["transaction_id", "account_id", "date", "amount", "currency", "type", "channel"],
         [("T1", "A1", D1, 10, "USD", "Deposit", "ATM"), ("T2", "A1", D1, 20, "USD", "Deposit", "ATM"),
          ("T3", "A2", D1, 30, "SAR", "Withdrawal", "ATM"), ("T4", "A2", D2, 40, "SAR", "Deposit", "Branch"),
          ("T5", "A3", D2, 50, "USD", "Deposit", "Branch"), ("T6", "A3", D2, 60, "USD", "Deposit", "Mobile")])
    # 2026-08 has no usable RWA (0), so the report must use 2026-07: the totals in the source document's worked example
    many("capital_positions", ["month", "tier1_capital", "tier2_capital", "risk_weighted_assets"],
         [("2026-06", 205000000, 37000000, 1950000000), ("2026-07", 207000000, 39000000, 1985000000),
          ("2026-08", 210000000, 40000000, 0)])
    cur.execute(
        """INSERT INTO scenario_snapshot (calculation_date, loans_by_currency, tier1_capital_usd, current_npl_pct)
           VALUES (%s, %s, %s, %s)""",
        (D2, psycopg2.extras.Json({"USD": 2880.0, "SAR": 450.0}), 100.0, 6.0),
    )


@pytest.fixture(scope="session")
def db():
    server = pgserver.get_server(pathlib.Path(tempfile.mkdtemp(prefix="pgdata_")), cleanup_mode="stop")
    conn = psycopg2.connect(server.get_uri())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    os.environ["DATABASE_URL"] = server.get_uri()
    os.environ["JWT_SECRET"] = "test-secret-not-for-real-use-0123456789abcdef"

    from seed_demo_users import seed
    seed(cur, PASSWORD)
    _load_data(cur)

    from seed_reports import seed as seed_reports
    seed_reports(conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), today=TODAY)
    yield cur
    conn.close()


@pytest.fixture(scope="session")
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth(client):
    response = client.post("/api/v1/auth/login", json={"email": "analyst@bankx.demo", "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
