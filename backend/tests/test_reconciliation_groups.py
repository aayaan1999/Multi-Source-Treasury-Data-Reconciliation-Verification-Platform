"""Core-system reconciliation grouped by cause (specs/reconciliation-groups.md, client point 1): which
breaks are important, how the rest group, one decision per group with carve-outs, which groups the CFO
must approve (specs/reconciliation-approvals.md), and single resolves as an admin override. Run
sign-off is tested in test_reconciliation_approvals.py. Tests run in file order."""
import os
import pathlib
import sys
from datetime import date, datetime, timezone

import psycopg2
import pytest

from conftest import PASSWORD

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import recon_groups_db  # noqa: E402
import recon_tasks_db  # noqa: E402

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
    for sql in ("DELETE FROM reconciliation_exceptions", "DELETE FROM reconciliation_corrections WHERE group_id IS NOT NULL",
                "DELETE FROM reconciliation_groups", "DELETE FROM camunda_process_tracking WHERE record_type = 'recon_group'"):
        db.execute(sql)


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


def test_group_facts_decide_title_severity_deadline_and_cfo_approval(db, conn, breaks):
    by_pattern = {(g["pattern"], g["important"]): g for g in recon_groups_db.fetch_unstarted(conn)}
    plus15 = by_pattern[("+15.00", False)]
    breaks_of = lambda g: recon_groups_db.breaks_of(conn, g["group_id"])     # noqa: E731
    assert recon_groups_db.title(plus15, breaks_of(plus15)) == "4 accounts: balance 15.00 higher in core banking"
    assert (plus15["total_difference"], plus15["cfo_required"]) == (60.0, False)
    band = by_pattern[("difference 100-1,000", False)]
    assert band["total_difference"] == -370.0 and band["cfo_required"] is False          # 850 in all: under 10,000
    assert recon_groups_db.title(band, breaks_of(band)) == "2 accounts: balance differs from core banking by 100-1,000"
    important = {g["pattern"]: g for g in by_pattern.values() if g["important"]}
    assert all(g["break_count"] == 1 and g["cfo_required"] for g in important.values())
    assert {p: g["cfo_reason"] for p, g in important.items()} == {
        "difference 10,000+": "a difference of 48,000.00", "different value": "a key field (segment)",
        "missing in our data": "a missing record"}
    assert recon_groups_db.title(important["difference 10,000+"], breaks_of(important["difference 10,000+"])) == \
        "Account A300: balance 48,000.00 higher in core banking"
    assert recon_groups_db.title(important["different value"], breaks_of(important["different value"])) == \
        'Customer C901: segment is "SME" in core banking, "Retail" here'
    assert recon_groups_db.title(important["missing in our data"], breaks_of(important["missing in our data"])) == \
        "Customer C900: in core banking but missing from our data"
    v = recon_groups_db.process_variables(important["missing in our data"], [])
    assert v["severity"] == "HIGH" and v["dueDate"] == "2026-09-25" and v["teamGroup"] == "operations" and v["cfoRequired"] is True
    assert recon_groups_db.process_variables(plus15, [])["dueDate"] == "2026-09-27"


def test_one_decision_for_the_group_except_the_carve_outs_which_regroup_alone(db, conn, breaks):
    db.execute("SELECT group_id FROM reconciliation_groups WHERE pattern = '+15.00'")
    gid = db.fetchone()[0]
    db.execute("UPDATE reconciliation_groups SET status = 'OPEN' WHERE group_id = %s", (gid,))     # its task has started
    db.execute("SELECT exception_id FROM reconciliation_exceptions WHERE entity_id = 'A103'")
    carved = db.fetchone()[0]
    assert recon_tasks_db.record_decision(conn, "recon_group", gid, "ACCEPT", 1, [carved])["needsCfo"] is False
    assert recon_tasks_db.record_decision(conn, "recon_group", gid, "ACCEPT", 1, [carved])["decisionOk"]    # a retried job
    assert not recon_tasks_db.record_decision(conn, "recon_group", gid, "DISMISS", 1, [])["decisionOk"]     # already decided
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


def test_each_source_sees_only_its_own_breaks_and_groups(client, auth, db, breaks):
    """The Reconciliation tab has one section per source (core banking, CRM); neither shows the other's rows."""
    db.execute("""INSERT INTO reconciliation_exceptions (source_system, entity_type, entity_id, field_name, source_value,
                  canonical_value, mismatch_type, status, detected_at, first_seen, last_seen, times_seen)
                  VALUES ('salesforce', 'customer', 'CN0008', 'name', 'Haddad Construction LLC', 'Haddad Contracting LLC',
                          'VALUE_MISMATCH', 'OPEN', now(), now(), now(), 1)""")
    crm = client.get(f"{API}/reconciliation", headers=auth, params={"source_system": "salesforce", "limit": 5000}).json()
    core = client.get(f"{API}/reconciliation", headers=auth, params={"source_system": "neon", "limit": 5000}).json()
    everything = client.get(f"{API}/reconciliation", headers=auth, params={"limit": 5000}).json()
    assert [r["entity_id"] for r in crm] == ["CN0008"]
    assert core and all(r["source_system"] == "neon" for r in core)
    assert len(everything) == len(core) + 1
    assert client.get(f"{API}/reconciliation/groups", headers=auth, params={"source_system": "salesforce"}).json() == []
    run = client.get(f"{API}/reconciliation/run", headers=auth, params={"source_system": "salesforce"}).json()
    assert run["source_system"] == "salesforce" and run["run_date"]
