"""Breach levels (specs/breach-levels.md, client point 8): levels, the consecutive-days rule,
escalation of one open breach per limit, early warnings as notifications that clear themselves,
and the limits the dashboard tiles read. Uses conftest's two KPI days (2026-09-20 and 09-21)."""
import os
import pathlib
import sys
from datetime import date

import psycopg2
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import breaches_db  # noqa: E402

API = "/api/v1"
TODAY = date(2026, 9, 24)
CAR = {"early_warning_value": 15, "threshold_value": 12.5, "regulatory_value": 12, "direction": "BELOW", "consecutive_days": 1}
NPL = {"early_warning_value": 3, "threshold_value": 5, "regulatory_value": None, "direction": "ABOVE", "consecutive_days": 3}


def test_the_most_severe_level_crossed_wins():
    assert breaches_db.level_for(CAR, 16) is None
    assert breaches_db.level_for(CAR, 14) == "EARLY_WARNING"
    assert breaches_db.level_for(CAR, 12.4) == "APPETITE"
    assert breaches_db.level_for(CAR, 11.9) == "REGULATORY"
    assert breaches_db.level_for(NPL, 9) == "APPETITE"          # no regulatory level set for NPL


def test_a_breach_counts_only_after_the_consecutive_days_and_at_the_level_held_throughout():
    assert breaches_db.sustained_level(NPL, [5.2, 5.1, 5.5]) == "APPETITE"          # 3 days over 5%
    assert breaches_db.sustained_level(NPL, [5.2, 4.6, 5.5]) == "EARLY_WARNING"     # one day only over 3%
    assert breaches_db.sustained_level(NPL, [5.2, 2.0, 5.5]) is None                # one day fine: no breach
    assert breaches_db.sustained_level(NPL, [5.2, 5.1]) is None                     # not enough days yet


@pytest.fixture(scope="module")
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


@pytest.fixture(scope="module")
def kpis(db):
    db.execute("SELECT calculation_date, car_pct, npl_ratio_pct FROM kpi_daily_summary")
    saved = db.fetchall()
    yield lambda day, **values: db.execute(
        "UPDATE kpi_daily_summary SET " + ", ".join(f"{k} = %s" for k in values) + " WHERE calculation_date = %s",
        (*values.values(), day),
    )
    for day, car, npl in saved:
        db.execute("UPDATE kpi_daily_summary SET car_pct = %s, npl_ratio_pct = %s WHERE calculation_date = %s", (car, npl, day))
    db.execute("DELETE FROM breaches")
    db.execute("UPDATE limits SET consecutive_days = 1")


def _open(db, metric):
    db.execute("""SELECT b.level, b.status, b.due_date FROM breaches b JOIN limits l ON l.limit_id = b.limit_id
                  WHERE l.metric_name = %s AND b.resolved_at IS NULL""", (metric,))
    return db.fetchall()


def test_one_breach_per_limit_that_escalates_from_warning_to_a_task(db, conn, kpis):
    kpis(date(2026, 9, 21), car_pct=14.0)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "capital_adequacy_ratio") == [("EARLY_WARNING", "WARNING", None)]      # a notification, no deadline
    assert not [b for b in breaches_db.untracked(conn) if b["metric_name"] == "capital_adequacy_ratio"]

    kpis(date(2026, 9, 21), car_pct=12.4)
    assert ("ESCALATED", "capital_adequacy_ratio", "APPETITE") in breaches_db.evaluate(conn, TODAY)
    assert _open(db, "capital_adequacy_ratio") == [("APPETITE", "OPEN", date(2026, 10, 8))]  # 14 days
    task = [b for b in breaches_db.untracked(conn) if b["metric_name"] == "capital_adequacy_ratio"][0]
    assert breaches_db.process_variables(task)["severity"] == "MEDIUM"

    kpis(date(2026, 9, 21), car_pct=11.8)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "capital_adequacy_ratio") == [("REGULATORY", "OPEN", date(2026, 10, 1))]  # half the days
    breaches_db.evaluate(conn, TODAY)
    assert len(_open(db, "capital_adequacy_ratio")) == 1                                     # never a duplicate
    db.execute("SELECT count(*) FROM audit_log WHERE action = 'ESCALATED'")
    assert db.fetchone()[0] == 2


def test_a_task_breach_stays_open_when_the_kpi_recovers_but_a_warning_clears_itself(db, conn, kpis):
    kpis(date(2026, 9, 21), car_pct=16.0)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "capital_adequacy_ratio") == [("REGULATORY", "OPEN", date(2026, 10, 1))]  # a person resolves it

    kpis(date(2026, 9, 21), npl_ratio_pct=4.0)                    # NPL early warning (over 3%)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "npl_ratio")[0][:2] == ("EARLY_WARNING", "WARNING")
    kpis(date(2026, 9, 21), npl_ratio_pct=2.0)
    assert ("CLEARED", "npl_ratio", "EARLY_WARNING") in breaches_db.evaluate(conn, TODAY)
    assert _open(db, "npl_ratio") == []


def test_the_consecutive_days_rule_applies_on_real_kpi_history(db, conn, kpis):
    db.execute("UPDATE limits SET consecutive_days = 2 WHERE metric_name = 'npl_ratio'")
    kpis(date(2026, 9, 20), npl_ratio_pct=4.0)
    kpis(date(2026, 9, 21), npl_ratio_pct=6.0)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "npl_ratio")[0][:2] == ("EARLY_WARNING", "WARNING")     # only 1 of 2 days over 5%
    kpis(date(2026, 9, 20), npl_ratio_pct=5.5)
    breaches_db.evaluate(conn, TODAY)
    assert _open(db, "npl_ratio")[0][:2] == ("APPETITE", "OPEN")             # 2 days running: a task


def test_the_tiles_get_the_same_limits_the_breach_check_uses(client, auth):
    rows = {r["kpi_key"]: r for r in client.get(f"{API}/kpi-summary/limits", headers=auth).json()}
    assert rows["car_pct"]["early_warning_value"] == 15 and rows["car_pct"]["threshold_value"] == 12.5
    assert rows["car_pct"]["regulatory_value"] == 12 and rows["npl_ratio_pct"]["regulatory_value"] is None
    assert all(r["is_placeholder"] for r in rows.values())
