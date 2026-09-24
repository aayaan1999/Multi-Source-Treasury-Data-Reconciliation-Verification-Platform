"""The CFO dashboard's country view (specs/cfo-country-view.md, FLOW-4)."""
from datetime import date

API = "/api/v1"


def test_country_view_is_the_latest_day_biggest_loan_book_first(client, auth, db):
    rows = [(date(2026, 9, 23), "Lebanon", 1, 1.0, 5.0, 0.0, 0.0, 1, 1.0),                 # an older day: not shown
            (date(2026, 9, 24), "Qatar", 2, 100.0, 100.0, 0.0, 0.0, 2, 30.0),
            (date(2026, 9, 24), "Lebanon", 3, 300.0, 900.0, 90.0, 10.0, 5, 70.0)]
    db.executemany("INSERT INTO country_performance_summary VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    try:
        body = client.get(f"{API}/kpi-summary/countries", headers=auth).json()
        assert [(r["country"], r["loans_usd"]) for r in body] == [("Lebanon", 900.0), ("Qatar", 100.0)]
        assert body[0]["npl_ratio_pct"] == 10.0
    finally:
        db.execute("DELETE FROM country_performance_summary")


def test_country_view_is_empty_not_an_error_before_the_first_run(client, auth):
    assert client.get(f"{API}/kpi-summary/countries", headers=auth).json() == []
