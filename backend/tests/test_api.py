import psycopg2
import pytest

from conftest import D2, PASSWORD

API = "/api/v1"


# ---- health & auth --------------------------------------------------------------------------
def test_health_reports_database_up(client):
    assert client.get(f"{API}/health").json() == {"status": "ok", "database": True}


def test_liveness_never_touches_the_database(client, monkeypatch):
    def down(*_, **__):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr("app.routers.health.query_one", down)
    assert client.get(f"{API}/live").json() == {"status": "alive"}
    assert client.get(f"{API}/health").status_code == 503  # ...while /health does report the outage


def test_login_returns_token_and_role(client):
    r = client.post(f"{API}/auth/login", json={"email": "Approver@BankX.demo", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "approver"
    assert "password_hash" not in body["user"]


def test_all_four_demo_users_can_log_in(client):
    for email, role in (("analyst", "analyst"), ("reviewer", "reviewer"), ("approver", "approver"), ("admin", "admin")):
        r = client.post(f"{API}/auth/login", json={"email": f"{email}@bankx.demo", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["user"]["role"] == role


@pytest.mark.parametrize("email,password", [("analyst@bankx.demo", "wrong"), ("nobody@bankx.demo", PASSWORD)])
def test_bad_credentials_rejected_with_same_message(client, email, password):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect email or password"


def test_user_without_password_cannot_log_in(client, db):
    db.execute("UPDATE users SET password_hash = NULL WHERE email = 'admin@bankx.demo'")
    try:
        r = client.post(f"{API}/auth/login", json={"email": "admin@bankx.demo", "password": ""})
        assert r.status_code == 401
    finally:
        from seed_demo_users import seed
        seed(db, PASSWORD)


def test_me_returns_token_claims(client, auth):
    body = client.get(f"{API}/auth/me", headers=auth).json()
    assert body["role"] == "analyst" and body["name"] == "Demo Analyst"


@pytest.mark.parametrize("path", [
    "/kpi-summary/latest", "/kpi-summary/history", "/portfolio/breakdown?dimension=product", "/portfolio/stage-summary",
    "/portfolio/top-exposures", "/portfolio/ageing", "/portfolio/ltv-distribution", "/portfolio/loans",
    "/scenario/snapshot", "/performance/branches", "/performance/segments", "/performance/products", "/auth/me",
])
def test_data_endpoints_require_a_token(client, path):
    assert client.get(API + path).status_code == 401
    assert client.get(API + path, headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_cors_allows_the_frontend_origin(client):
    r = client.options(f"{API}/kpi-summary/latest", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ---- screen 1 -------------------------------------------------------------------------------
def test_kpi_latest_is_newest_date_with_assumptions(client, auth):
    body = client.get(f"{API}/kpi-summary/latest", headers=auth).json()
    assert body["calculation_date"] == D2.isoformat() and body["car_pct"] == 13.5
    assert body["assumptions_applied"] == ["DEPOSIT_RATE_BY_TYPE placeholder (nim_pct)"]


def test_kpi_history_window(client, auth):
    assert len(client.get(f"{API}/kpi-summary/history?days=1", headers=auth).json()) == 1
    rows = client.get(f"{API}/kpi-summary/history?days=30", headers=auth).json()
    assert [r["calculation_date"] for r in rows] == ["2026-09-20", "2026-09-21"]


def test_kpi_history_rejects_out_of_range_days(client, auth):
    assert client.get(f"{API}/kpi-summary/history?days=0", headers=auth).status_code == 422


# ---- screen 2 -------------------------------------------------------------------------------
def test_breakdown_uses_latest_date_only_and_sorts_by_size(client, auth):
    rows = client.get(f"{API}/portfolio/breakdown?dimension=product", headers=auth).json()
    assert [r["dimension_value"] for r in rows] == ["Corporate Loan", "Mortgage"]  # older OldProduct row excluded
    assert client.get(f"{API}/portfolio/breakdown?dimension=currency", headers=auth).json()[0]["dimension_value"] == "USD"


def test_breakdown_rejects_unknown_dimension(client, auth):
    assert client.get(f"{API}/portfolio/breakdown?dimension=bogus", headers=auth).status_code == 422


def test_stage_summary_sorted_by_stage(client, auth):
    assert [r["stage"] for r in client.get(f"{API}/portfolio/stage-summary", headers=auth).json()] == [1, 2, 3]


def test_top_exposures_largest_first(client, auth):
    assert [r["customer_id"] for r in client.get(f"{API}/portfolio/top-exposures", headers=auth).json()] == ["C3", "C1"]


def test_ageing_and_ltv_use_business_order_not_alphabetical(client, auth):
    ageing = [r["bucket"] for r in client.get(f"{API}/portfolio/ageing", headers=auth).json()]
    ltv = [r["bucket"] for r in client.get(f"{API}/portfolio/ltv-distribution", headers=auth).json()]
    assert ageing == ["Current", "31-60", "90-180", "180+"]
    assert ltv == ["<50%", "50-80%", "80-100%", ">100%"]


def test_loans_list_sorted_and_joined_to_customer(client, auth):
    body = client.get(f"{API}/portfolio/loans", headers=auth).json()
    assert body["total"] == 4 and [i["loan_id"] for i in body["items"]] == ["L3", "L1", "L2", "L4"]
    assert body["items"][0]["customer_name"] == "Cy" and body["items"][0]["segment"] == "Corporate"


@pytest.mark.parametrize("query,expected", [
    ("product=Mortgage", ["L1"]),
    ("currency=SAR", ["L2"]),
    ("stage=1", ["L1", "L4"]),
    ("segment=Retail", ["L1", "L4"]),
    ("branch_id=B1", ["L3", "L1", "L4"]),
    ("min_days_past_due=45", ["L3", "L2"]),
    ("stage=1&currency=USD&branch_id=B1", ["L1", "L4"]),
])
def test_loans_filters(client, auth, query, expected):
    body = client.get(f"{API}/portfolio/loans?{query}", headers=auth).json()
    assert [i["loan_id"] for i in body["items"]] == expected and body["total"] == len(expected)


def test_loans_pagination_reports_total(client, auth):
    body = client.get(f"{API}/portfolio/loans?limit=2&offset=1", headers=auth).json()
    assert body["total"] == 4 and [i["loan_id"] for i in body["items"]] == ["L1", "L2"]


def test_loans_input_is_parameterised_not_interpolated(client, auth):
    r = client.get(f"{API}/portfolio/loans", params={"product": "x' OR '1'='1"}, headers=auth)
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get(f"{API}/portfolio/loans", headers=auth).json()["total"] == 4  # table untouched


def test_loans_rejects_bad_paging_and_stage(client, auth):
    for bad in ("stage=4", "limit=0", "limit=501", "offset=-1"):
        assert client.get(f"{API}/portfolio/loans?{bad}", headers=auth).status_code == 422


# ---- screen 4 & 5 ---------------------------------------------------------------------------
def test_scenario_snapshot_returns_json_maps_as_objects(client, auth):
    body = client.get(f"{API}/scenario/snapshot", headers=auth).json()
    assert body["loans_by_currency"] == {"USD": 2880.0, "SAR": 450.0} and body["tier1_capital_usd"] == 100.0


def test_performance_endpoints_sorted_by_profit(client, auth):
    assert [r["branch_id"] for r in client.get(f"{API}/performance/branches", headers=auth).json()] == ["B2", "B1"]
    assert [r["segment"] for r in client.get(f"{API}/performance/segments", headers=auth).json()] == ["SME", "Retail"]
    assert [r["product"] for r in client.get(f"{API}/performance/products", headers=auth).json()] == ["SME Loan", "Mortgage"]


# ---- empty and failure states ---------------------------------------------------------------
def test_empty_gold_tables_give_404_or_empty_list_not_500(client, auth, db):
    db.execute("DELETE FROM scenario_snapshot")
    db.execute("DELETE FROM kpi_daily_summary")
    db.execute("DELETE FROM branch_performance_summary")
    assert client.get(f"{API}/scenario/snapshot", headers=auth).status_code == 404
    assert client.get(f"{API}/kpi-summary/latest", headers=auth).status_code == 404
    assert client.get(f"{API}/kpi-summary/history", headers=auth).json() == []
    assert client.get(f"{API}/performance/branches", headers=auth).json() == []


def test_database_outage_returns_503_and_health_degrades(client, auth, monkeypatch):
    def down(*_, **__):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr("app.routers.kpi.query_one", down)
    monkeypatch.setattr("app.routers.health.query_one", down)
    assert client.get(f"{API}/kpi-summary/latest", headers=auth).status_code == 503
    assert client.get(f"{API}/health").status_code == 503
