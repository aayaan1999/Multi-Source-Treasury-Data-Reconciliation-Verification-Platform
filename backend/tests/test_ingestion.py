"""Data Ingestion screen (specs/screen-data-ingestion.md): real figures from the latest pipeline run when
there is one, demo content (labelled) for what doesn't exist yet."""
from datetime import datetime, timezone

import pytest

from app.routers import ingestion
from conftest import PASSWORD

API = "/api/v1"


@pytest.fixture
def auth(client):
    """The Data ingestion screen is the Platform Administrator's (specs/user-roles.md)."""
    token = client.post(f"{API}/auth/login", json={"email": "admin@bankx.demo", "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_without_a_pipeline_run_everything_is_labelled_demo(client, auth, monkeypatch):
    monkeypatch.setattr(ingestion, "_latest_run", lambda: [])     # a database the pipeline hasn't loaded yet
    body = client.get(f"{API}/ingestion/overview", headers=auth).json()
    assert body["stats"]["demo"] and body["recent"]["demo"] and body["schedules"]["demo"]
    assert body["stats"]["failed"] == 1 and "authentication expired" in body["stats"]["failed_example"]
    assert not body["connectors"]["demo"]                              # sources are real state now


def test_the_latest_run_gives_real_counts_per_source(client, auth, db):
    old = datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)
    new = datetime(2026, 9, 28, 7, 22, tzinfo=timezone.utc)
    rows = [("k-old", "b1", "Lebanon", "transactions", 999, 999, 0, None, old),
            ("k1", "b2", "Lebanon", "transactions", 1419, 1416, 3, None, new),
            ("k2", "b2", "Qatar", "accounts", 31, 31, 0, None, new),
            ("k3", "b2", "Group", "fx_rates", 0, 0, 0, "No rows delivered", new)]
    db.executemany("""INSERT INTO pipeline_reconciliation (recon_key, ingest_batch_id, source_system, source_country, source_table,
                      received_rows, clean_rows, rejected_rows, has_gap, note, detected_at)
                      VALUES (%s, %s, 'CORE_CSV', %s, %s, %s, %s, %s, false, %s, %s)""", rows)
    try:
        body = client.get(f"{API}/ingestion/overview", headers=auth).json()
        stats = body["stats"]
        assert not stats["demo"] and not body["recent"]["demo"]
        assert (stats["files"], stats["received"], stats["kept"], stats["held"], stats["failed"]) == (3, 1450, 1447, 3, 1)
        assert stats["failed_example"] == "Group Core Banking · fx_rates.csv: No rows delivered"
        assert stats["run_at"].startswith("2026-09-28T07:22")
        by_data = {r["data"]: r for r in body["recent"]["items"]}
        assert by_data["transactions.csv"]["source"] == "Lebanon Core Banking" and by_data["transactions.csv"]["held"] == 3
        assert by_data["fx_rates.csv"]["status"] == "failed" and by_data["accounts.csv"]["status"] == "success"
        assert body["schedules"]["demo"] and body["trigger"] == "On file arrival"     # still placeholders
    finally:
        db.execute("DELETE FROM pipeline_reconciliation WHERE recon_key IN ('k-old', 'k1', 'k2', 'k3')")


def test_the_assistant_side_panel_lists_what_it_reads_and_the_users_scope(client, auth):
    body = client.get(f"{API}/ask/context", headers=auth).json()
    areas = {a["key"]: a for a in body["areas"]}
    assert areas["kpi"]["answerable"] and areas["load"]["answerable"]
    assert not areas["reconciliation"]["answerable"] and not areas["reports"]["answerable"]
    assert body["scope"]["access"] == "Platform Administrator: all data"


def test_needs_a_login(client):
    assert client.get(f"{API}/ingestion/overview").status_code == 401
    assert client.get(f"{API}/ask/context").status_code == 401
