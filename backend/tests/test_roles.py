"""Who sees what (specs/user-roles.md): the server refuses a screen's data to a role that doesn't use it, the
Internal Auditor can read but not change anything, and the seed renames the old logins in place with each user's own demo password."""
import pathlib
import sys

import psycopg2.extras
import pytest

from conftest import PASSWORD

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import recon_tasks_db  # noqa: E402

API = "/api/v1"


def headers(client, who):
    token = client.post(f"{API}/auth/login", json={"email": f"{who}@bankx.demo", "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# (login, path, allowed) - one screen each role uses and one it doesn't
@pytest.mark.parametrize("who, path, allowed", [
    ("cfo", "/portfolio/stage-summary", True), ("cfo", "/ingestion/overview", False),
    ("cro", "/scenario/snapshot", True), ("cro", "/reconciliation/runs", False),
    ("recon.analyst", "/reconciliation/runs", True), ("recon.analyst", "/portfolio/stage-summary", False),
    ("reporting", "/reports", True), ("reporting", "/performance/branches", False),
    ("compliance", "/kpi-summary/latest", True), ("compliance", "/reports", False),
    ("auditor", "/reports", True), ("auditor", "/scenario/snapshot", False),
    ("admin", "/ingestion/overview", True), ("admin", "/portfolio/stage-summary", False),
])
def test_each_role_reaches_its_own_screens_only(client, who, path, allowed):
    r = client.get(f"{API}{path}", headers=headers(client, who))
    assert (r.status_code != 403) is allowed, (who, path, r.status_code, r.text[:120])
    if not allowed:
        assert "doesn't use this screen" in r.json()["detail"]


def test_the_auditor_reads_but_changes_nothing(client):
    auditor = headers(client, "auditor")
    assert client.get(f"{API}/workflow/audit-log", headers=auditor).status_code == 200
    body = {"source_table": "customers", "record_key": "C1", "flag_label": "X", "comment_text": "looks fine"}
    r = client.post(f"{API}/workflow/exceptions/comments", headers=auditor, json=body)
    assert r.status_code == 403 and "can look but not change anything" in r.json()["detail"]
    reports = client.get(f"{API}/reports", headers=auditor).json()
    export = client.post(f"{API}/reports/{reports[0]['report_instance_id']}/export/excel", headers=auditor)
    assert export.status_code != 403                                    # exporting is reading, not refused


def test_the_auditor_cant_decide_a_reconciliation_task(db):
    db.execute("SELECT user_id FROM users WHERE email = 'auditor@bankx.demo'")
    auditor = db.fetchone()[0]
    conn = psycopg2.connect(db.connection.dsn)
    try:
        result = recon_tasks_db.record_decision(conn, "reconciliation", 1, "ACCEPT", auditor)
    finally:
        conn.close()
    assert result == {"decisionOk": False, "decisionError": "The Internal Auditor can look but not decide (specs/user-roles.md)."}


def test_the_seed_renames_old_logins_in_place_and_gives_each_its_demo_password(client, db):
    from seed_demo_users import seed
    db.execute("SELECT user_id FROM users WHERE email = 'cfo@bankx.demo'")
    cfo_id = db.fetchone()[0]
    db.execute("UPDATE users SET email = 'approver@bankx.demo' WHERE user_id = %s", (cfo_id,))    # as before the change
    try:
        seed(db)                                                        # no shared password: each user's own
        db.execute("SELECT user_id FROM users WHERE email = 'cfo@bankx.demo'")
        assert db.fetchone()[0] == cfo_id                               # same person, so the audit trail still fits
        r = client.post(f"{API}/auth/login", json={"email": "cfo@bankx.demo", "password": "BankX-Cfo-2026"})
        assert r.status_code == 200
        assert client.post(f"{API}/auth/login", json={"email": "cro@bankx.demo", "password": "BankX-Cfo-2026"}).status_code == 401
    finally:
        seed(db, PASSWORD)
