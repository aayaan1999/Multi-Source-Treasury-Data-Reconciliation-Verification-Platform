"""Core-system reconciliation grouped by cause (specs/reconciliation-groups.md, client point 1): which
breaks are important, how the rest group, one decision per group with carve-outs, the second-approval
rule, run sign-off, and single resolves as an admin override. Tests run in file order."""
import os
import pathlib
import sys
from datetime import date, datetime, timezone

import psycopg2
import pytest

from conftest import PASSWORD

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import recon_groups_db  # noqa: E402

API = "/api/v1"
TODAY = date(2026, 9, 24)
SEEN = datetime(2026, 9, 24, 6, tzinfo=timezone.utc)


def brk(entity_type, entity_id, field, source, ours, mismatch="VALUE_MISMATCH", status="OPEN"):
    return ("neon", entity_type, entity_id, field, source, ours, mismatch, status, SEEN, SEEN, SEEN)


BREAKS = [
    # four balances off by exactly +15: one "+15.00" group
    *[brk("account", f"A10{i}", "balance", "1015.00", "1000.00") for i in range(4)],
    # two different mid-size differences: one "difference 100-1,000" group
    brk("account", "A200", "balance", "1240.00", "1000.00"),
    brk("account", "A201", "balance", "390.00", "1000.00"),
    # always on their own: a big amount, a missing record, a key field
    brk("account", "A300", "balance", "49000.00", "1000.00"),
    brk("customer", "C900", None, None, None, mismatch="MISSING_IN_CANONICAL"),
    brk("customer", "C901", "segment", "SME", "Retail"),
    # cleared automatically by the notebook: never grouped
    brk("customer", "C902", "name", "AL-HASSAN", "Al Hassan", status="AUTO_ACCEPTED"),
]


@pytest.fixture(scope="module")
def breaks(db):
    db.executemany(
        """INSERT INTO reconciliation_exceptions (source_system, entity_type, entity_id, field_name, source_value,
               canonical_value, mismatch_type, status, detected_at, first_seen, last_seen)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        BREAKS,
    )
    yield
    for sql in ("DELETE FROM reconciliation_exceptions", "DELETE FROM reconciliation_groups",
                "DELETE FROM reconciliation_signoffs", "DELETE FROM camunda_process_tracking WHERE record_type = 'recon_group'"):
        db.execute(sql)
    db.execute("UPDATE app_settings SET value = jsonb_set(value, '{second_approval_total}', '100000') WHERE key = 'recon.rules'")


@pytest.fixture(scope="module")
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


def login(client, who):
    return {"Authorization": f"Bearer {client.post(f'{API}/auth/login', json={'email': f'{who}@bankx.demo', 'password': PASSWORD}).json()['access_token']}"}


def _groups(db):
    db.execute("SELECT pattern, important, break_count FROM reconciliation_groups ORDER BY important, break_count DESC, pattern")
    return db.fetchall()


def test_breaks_group_by_cause_and_important_ones_stand_alone(db, conn, breaks):
    db.execute("UPDATE app_settings SET value = jsonb_set(value, '{second_approval_total}', '200') WHERE key = 'recon.rules'")
    assert recon_groups_db.create_groups(conn, TODAY) == 5
    assert _groups(db) == [
        ("+15.00", False, 4),                     # 4 x the same +15: one group
        ("difference 100-1,000", False, 2),       # +240 and -610: one size band
        ("difference 10,000+", True, 1),          # 48,000: too big to decide in bulk
        ("different value", True, 1),             # segment is a key field
        ("missing in our data", True, 1),         # a missing record
    ]
    db.execute("SELECT count(*) FROM reconciliation_exceptions WHERE group_id IS NULL")
    assert db.fetchone()[0] == 1                                 # only the auto-cleared break
    assert recon_groups_db.create_groups(conn, TODAY) == 0


def test_group_facts_decide_title_severity_deadline_and_second_approval(db, conn, breaks):
    by_pattern = {(g["pattern"], g["important"]): g for g in recon_groups_db.fetch_unstarted(conn)}
    plus15 = by_pattern[("+15.00", False)]
    assert recon_groups_db.title(plus15) == "Account balance +15.00 · 4 accounts · neon"
    assert (plus15["total_difference"], plus15["requires_second_approval"]) == (60.0, False)
    band = by_pattern[("difference 100-1,000", False)]
    assert band["total_difference"] == -370.0 and band["requires_second_approval"] is True   # |240| + |-610| = 850 >= 200
    important = [g for g in by_pattern.values() if g["important"]]
    assert len(important) == 3 and all(g["break_count"] == 1 and not g["requires_second_approval"] for g in important)
    v = recon_groups_db.process_variables(important[0])
    assert v["severity"] == "HIGH" and v["dueDate"] == "2026-09-25" and v["teamGroup"] == "operations"
    assert recon_groups_db.process_variables(plus15)["dueDate"] == "2026-09-27"


def test_one_decision_for_the_group_except_the_carve_outs_which_regroup_alone(db, conn, breaks):
    db.execute("SELECT group_id FROM reconciliation_groups WHERE pattern = '+15.00'")
    gid = db.fetchone()[0]
    db.execute("SELECT exception_id FROM reconciliation_exceptions WHERE entity_id = 'A103'")
    carved = db.fetchone()[0]
    recon_groups_db.decide(conn, gid, "ACCEPT", [carved], 1, 3)
    recon_groups_db.decide(conn, gid, "DISMISS", [], 1, 3)          # a retried job changes nothing
    db.execute("SELECT entity_id, status, group_id IS NULL, carved_out FROM reconciliation_exceptions WHERE entity_id LIKE 'A10%' ORDER BY entity_id")
    assert db.fetchall() == [("A100", "ACCEPTED", False, False), ("A101", "ACCEPTED", False, False),
                             ("A102", "ACCEPTED", False, False), ("A103", "OPEN", True, True)]
    assert recon_groups_db.create_groups(conn, TODAY) == 1          # the carve-out, on its own
    db.execute("SELECT break_count, important FROM reconciliation_groups WHERE group_id = (SELECT group_id FROM reconciliation_exceptions WHERE entity_id = 'A103')")
    assert db.fetchone() == (1, False)
    db.execute("SELECT count(*) FROM audit_log WHERE object_type = 'reconciliation_exception' AND new_value = %s", (f"group #{gid}",))
    assert db.fetchone()[0] == 3


def test_the_tab_lists_groups_and_a_group_opens_onto_its_breaks(client, auth, breaks):
    groups = client.get(f"{API}/reconciliation/groups", headers=auth).json()
    assert groups[0]["important"] is True                           # important first
    detail = client.get(f"{API}/reconciliation/groups/{groups[0]['group_id']}", headers=auth).json()
    assert detail["break_count"] == len(detail["breaks"]) == 1
    rows = client.get(f"{API}/reconciliation?limit=5000", headers=auth).json()
    assert {r["status"] for r in rows} >= {"AUTO_ACCEPTED", "ACCEPTED", "OPEN"}
    assert all("last_seen" in r and "recurring" in r for r in rows)


def test_single_breaks_are_decided_in_tasks_only_an_admin_can_override(client, auth, breaks, db):
    db.execute("SELECT exception_id FROM reconciliation_exceptions WHERE status = 'OPEN' LIMIT 1")
    eid = db.fetchone()[0]
    assert client.post(f"{API}/reconciliation/{eid}/resolve", headers=auth, json={"status": "ACCEPTED"}).status_code == 403
    admin = login(client, "admin")
    assert client.post(f"{API}/reconciliation/{eid}/resolve", headers=admin, json={"status": "ACCEPTED", "resolution_note": "override"}).status_code == 200


def test_run_sign_off_needs_a_note_with_important_breaks_open_and_a_second_person(client, auth, breaks):
    run = client.get(f"{API}/reconciliation/run", headers=auth).json()
    assert run["run_date"] == "2026-09-24" and run["auto_cleared"] == 1 and run["important_open"] == 3
    r = client.post(f"{API}/reconciliation/run/submit", headers=auth, json={})
    assert r.status_code == 400 and "important" in r.json()["detail"]
    assert client.post(f"{API}/reconciliation/run/submit", headers=auth, json={"note": "3 known, being worked"}).json() == {"status": "SUBMITTED"}
    assert client.post(f"{API}/reconciliation/run/signoff", headers=auth, json={"decision": "SIGN_OFF"}).status_code == 403   # analyst
    cfo = login(client, "approver")
    r = client.post(f"{API}/reconciliation/run/signoff", headers=cfo, json={"decision": "RETURN"})
    assert r.status_code == 400                                     # a return needs a reason
    assert client.post(f"{API}/reconciliation/run/signoff", headers=cfo, json={"decision": "SIGN_OFF", "note": "ok"}).json() == {"status": "SIGNED_OFF"}
    run = client.get(f"{API}/reconciliation/run", headers=auth).json()
    assert run["signoff"]["status"] == "SIGNED_OFF" and run["signoff"]["signed_by_name"] == "Demo Approver"


def test_the_preparer_cant_sign_off_their_own_run(client, db, breaks):
    db.execute("DELETE FROM reconciliation_signoffs")
    cfo = login(client, "approver")
    client.post(f"{API}/reconciliation/run/submit", headers=cfo, json={"note": "prepared by the CFO"})
    r = client.post(f"{API}/reconciliation/run/signoff", headers=cfo, json={"decision": "SIGN_OFF"})
    assert r.status_code == 409 and "prepared" in r.json()["detail"]
