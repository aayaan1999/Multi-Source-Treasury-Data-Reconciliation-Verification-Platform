"""Task cases, severity, digest and deadlines (specs/task-cases.md, client point 6): the bridge's
Postgres side (camunda/bridge/cases_db.py) and the endpoints the Tasks screen uses. Uses conftest's
transactions (T1-T6 on accounts A1-A3). Tests run in file order."""
import os
import pathlib
import sys
from datetime import date, datetime, timezone

import psycopg2
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import cases_db  # noqa: E402

API = "/api/v1"
TODAY = date(2026, 9, 24)
TS = datetime(2026, 9, 24, 8, tzinfo=timezone.utc)


def team(flag_type, _table):   # the same mapping as poll_worker.flag_category, without importing Zeebe
    return {"SUSPICIOUS": "FRAUD", "THRESHOLD": "COMPLIANCE"}.get(flag_type, "OPERATIONS")


@pytest.fixture(scope="module")
def flags(db):
    db.executemany(
        "INSERT INTO flagged_transactions VALUES (%s, %s, %s, %s, %s, %s)",
        [
            ("T5", "VELOCITY_BREACH", "SUSPICIOUS", "3 txns", "PENDING_REVIEW", TS),       # A3, 21 Sep: one case,
            ("T5", "STRUCTURING_PATTERN", "SUSPICIOUS", "band", "PENDING_REVIEW", TS),     #   3 flags, 2 rules -> HIGH
            ("T6", "VELOCITY_BREACH", "SUSPICIOUS", "3 txns", "PENDING_REVIEW", TS),
            ("T1", "LARGE_AMOUNT", "THRESHOLD", "over limit", "PENDING_REVIEW", TS),       # A1: 1 flag -> MEDIUM
            ("T3", "DUPLICATE_TRANSACTION", "OPERATIONAL", "dup", "PENDING_REVIEW", TS),   # A2: 1 flag -> LOW, digest
            ("T2", "LARGE_AMOUNT", "THRESHOLD", "over limit", "APPROVED", TS),             # already reviewed: skipped
            ("T4", "LARGE_AMOUNT", "THRESHOLD", "over limit", "PENDING_REVIEW", TS),       # has an old one-flag task: skipped
        ],
    )
    db.execute("""INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
                  VALUES ('fraud', 'transactions', 'T4', 'LARGE_AMOUNT', 1)""")
    yield
    for sql in ("DELETE FROM task_case_flags", "DELETE FROM task_cases", "DELETE FROM camunda_process_tracking",
                "DELETE FROM review_outcomes", "DELETE FROM flagged_transactions"):
        db.execute(sql)


@pytest.fixture(scope="module")
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


def _cases(db):
    db.execute("SELECT account_id, flag_type, flag_count, severity, severity_score, team, status, due_date FROM task_cases ORDER BY case_id")
    return db.fetchall()


def test_flags_group_into_one_case_per_account_day_and_type(db, conn, flags):
    assert cases_db.create_cases(conn, team, TODAY) == 3
    by_account = {c[0]: c for c in _cases(db)}
    assert set(by_account) == {"A3", "A1", "A2"}                                   # T2 reviewed, T4 already tracked
    assert by_account["A3"][1:7] == ("SUSPICIOUS", 3, "HIGH", 5, "FRAUD", "PENDING")
    assert by_account["A1"][1:7] == ("THRESHOLD", 1, "MEDIUM", 2, "COMPLIANCE", "PENDING")
    assert by_account["A2"][1:7] == ("OPERATIONAL", 1, "LOW", 1, "OPERATIONS", "DIGEST")
    assert by_account["A3"][7] == date(2026, 9, 26) and by_account["A1"][7] == date(2026, 9, 29)   # 2 and 5 days


def test_grouping_again_changes_nothing(conn, flags):
    assert cases_db.create_cases(conn, team, TODAY) == 0


def test_only_high_and_medium_cases_become_tasks_with_a_title_team_and_due_date(conn, flags):
    unstarted = cases_db.fetch_unstarted(conn)
    assert [(c["account_id"], c["severity"]) for c in unstarted] == [("A3", "HIGH"), ("A1", "MEDIUM")]
    v = cases_db.process_variables(unstarted[0])
    assert v["recordType"] == "fraud_case" and v["flagCategory"] == "FRAUD" and v["dueDate"] == "2026-09-26"
    assert v["title"] == "A3 · 21 Sep 2026 · 3 Suspicious flags"


def test_starting_a_case_tracks_every_flag_so_none_is_started_twice(db, conn, flags):
    high = cases_db.fetch_unstarted(conn)[0]
    cases_db.record_started(conn, high["case_id"], 2251799813685300)
    cases_db.record_started(conn, high["case_id"], 2251799813685300)
    db.execute("SELECT count(*) FROM camunda_process_tracking WHERE process_instance_key = 2251799813685300")
    assert db.fetchone()[0] == 3
    assert [c["account_id"] for c in cases_db.fetch_unstarted(conn)] == ["A1"]


def test_a_new_flag_after_the_case_started_opens_a_new_case(db, conn, flags):
    db.execute("INSERT INTO flagged_transactions VALUES ('T6', 'STRUCTURING_PATTERN', 'SUSPICIOUS', 'band', 'PENDING_REVIEW', %s)", (TS,))
    assert cases_db.create_cases(conn, team, TODAY) == 1
    db.execute("SELECT count(*) FROM task_cases WHERE account_id = 'A3'")
    assert db.fetchone()[0] == 2


def test_the_case_popup_lists_every_flag_with_its_transaction(client, auth, conn, flags):
    case_id = [c for c in cases_db.fetch_unstarted(conn)][0]["case_id"]   # any case works; use the API for A3's first
    body = client.get(f"{API}/workflow/cases/{case_id}", headers=auth).json()
    assert body["flag_count"] == len(body["flags"])
    assert client.get(f"{API}/workflow/cases/999999", headers=auth).status_code == 404


def test_one_decision_closes_every_flag_in_the_case_once(db, conn, flags):
    db.execute("SELECT case_id FROM task_cases WHERE account_id = 'A3' AND status = 'OPEN'")
    case_id = db.fetchone()[0]
    cases_db.close_case(conn, case_id, "APPROVED", 3)
    cases_db.close_case(conn, case_id, "REJECTED", 3)                     # a retried job changes nothing
    db.execute("""SELECT f.status FROM flagged_transactions f JOIN task_case_flags c
                  ON c.transaction_id = f.transaction_id AND c.flag_label = f.flag_label WHERE c.case_id = %s""", (case_id,))
    assert [s for (s,) in db.fetchall()] == ["APPROVED"] * 3
    db.execute("SELECT count(*) FROM review_outcomes WHERE outcome = 'APPROVED'")
    assert db.fetchone()[0] == 3


def test_the_digest_lists_low_cases_and_one_can_be_raised_as_a_task(client, auth, conn, flags):
    digest = client.get(f"{API}/workflow/digest", headers=auth).json()
    assert [(c["account_id"], c["severity"]) for c in digest] == [("A2", "LOW")]
    case_id = digest[0]["case_id"]
    assert client.post(f"{API}/workflow/digest/{case_id}/raise", headers=auth).json() == {"status": "PENDING"}
    assert client.post(f"{API}/workflow/digest/{case_id}/raise", headers=auth).status_code == 409
    assert case_id in [c["case_id"] for c in cases_db.fetch_unstarted(conn)]


def test_the_policy_is_readable_and_marked_as_placeholders(client, auth):
    rows = {r["key"]: r for r in client.get(f"{API}/workflow/policy", headers=auth).json()}
    assert rows["task.severity"]["value"]["high_min"] == 4 and rows["task.due_days"]["value"]["HIGH"] == 2
    assert all(r["is_placeholder"] for r in rows.values())


def test_comments_can_be_added_on_a_case(client, auth, db, flags):
    db.execute("SELECT min(case_id) FROM task_cases")
    key = {"source_table": "task_cases", "record_key": str(db.fetchone()[0]), "flag_label": "SUSPICIOUS"}
    assert client.post(f"{API}/workflow/exceptions/comments", headers=auth, json={**key, "comment_text": "checked"}).status_code == 200
